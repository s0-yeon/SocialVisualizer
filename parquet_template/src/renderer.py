# 소셜 데이터 유형별 config(JSON)와 Jinja2 템플릿(.j2)을 기반으로, GraphRAG 워크플로우별 프롬프트 텍스트와 설정 파일(settings.yaml)을 렌더링하여 저장한다.

#This script renders workflow-specific prompt texts and a settings.yaml configuration file for GraphRAG, based on domain-specific JSON configs and Jinja2 (.j2) templates.

import json
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from pathlib import Path

class PromptTemplate:
    WORKFLOW_NAMES = {
        "extract_graph", "summarize_descriptions", "summarize_attachment", "extract_claims", "community_reports", "local_search", "global_search"
    }
    NESTED_WORKFLOWS = {
        "global_search" : ["map", "reduce", "knowledge"]
    }

    # 생성자:  config 경로/출력 경로를 설정하고, .j2 템플릿을 로드할 Jinja2 환경을 생성
    def __init__(self, domain: str):
        self.domain = domain
        self.config_path = Path(__file__).parent/"configs"/f"{domain}.json"
        self.output_dir = Path(__file__).parent.parent/"rendered"/domain

        if not self.config_path.exists():
            raise FileNotFoundError(f"config not found: {self.config_path}")

        # prompts/ 디렉터리에서 .j2 템플릿을 로드하는 Jinja2 환경 생성 (미정의 변수 참조 시 에러 발생, 불필요한 공백/줄바꿈 제거)
        self.env = Environment(loader=FileSystemLoader(str(Path(__file__).parent/"prompts")), trim_blocks=True, lstrip_blocks=True, undefined=StrictUndefined,)

    # 렌더링 결과물(rendered/{domain}/)을 담을 디렉터리를 준비, 없으면 생성
    def _ensure_output_dir(self) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        return self.output_dir

    # 프롬프트 템플릿(name.j2)를 렌더링해서 prompts/name.txt로 저장
    def _render_one_prompt(self, name: str, context: dict, prompts_dir: Path): 
        template = self.env.get_template(f"{name}.j2")
        rendered = template.render(**context)   # j2 템플릿의 context에 실제 값을 채워 완성된 문자열을 리턴

        output_path = prompts_dir/f"{name}.txt"
        output_path.write_text(rendered, encoding="utf-8")
        print(f"[render] {output_path}")

    # 설정 파일 템플릿(settings.yaml)을 렌더링해서 prompt/settings.yaml로 저장
    def _render_settings(self, config: dict): 
        template = self.env.get_template("settings.j2")
        rendered = template.render(**config) 

        # assert "{{" not in rendered and "{%" not in rendered, f"unrendered tag left in settings.yaml"     # 렌더링 성공 여부 검사. 잔존 태그가 있으면 에러 발생

        output_dir =  self._ensure_output_dir()     # prompts/ 형제
        output_path = output_dir/f"settings.yaml"
        output_path.write_text(rendered, encoding="utf-8")
        print(f"[render] {output_path}")

    # config.json을 읽어서 워크플로우별 프롬프트 템플릿과 설정 파일을 렌더링
    def render(self):
        with open(self.config_path, encoding="utf-8") as file:
            config = json.load(file)

        # workflow를 제외한 나머지 키들이 공유하는 값
        shared = {k: v for k, v in config.items() if k not in self.WORKFLOW_NAMES}  

        prompts_dir = self._ensure_output_dir()/"prompts"
        prompts_dir.mkdir(parents=True, exist_ok=True)

        for workflow in self.WORKFLOW_NAMES:
            value = config.get(workflow)
            if value is None:
                print(f"[skip] {self.domain}: {workflow} not configured")
                continue

            if workflow in self.NESTED_WORKFLOWS:   # 하위 구조를 가진 경우 (global_search)
                for sub in  self.NESTED_WORKFLOWS[workflow]:
                    sub_value = value.get(sub)
                    if sub_value is None:
                        print(f"[skip] {self.domain}: {workflow}.{sub} not configured")
                        continue
                    self._render_one_prompt(f"{workflow}_{sub}", {**shared, **sub_value}, prompts_dir)
            else:
                self._render_one_prompt(workflow, {**shared, **value}, prompts_dir)

        # settings.j2 렌더링
        self._render_settings(config)

# configs/ 밑의 모든 도메인 config를 스캔해서, settings.yaml이 없거나 config·.j2 템플릿보다 오래된(즉 수정 후 아직 반영 안 된) 도메인만 렌더링
def render_all_prompts():
    configs_dir = Path(__file__).parent/"configs"
    templates_dir = Path(__file__).parent/"prompts"
    rendered_dir = Path(__file__).parent.parent/"rendered"

    template_mtime = max((p.stat().st_mtime for p in templates_dir.glob("*.j2")), default=0)

    for config_path in configs_dir.glob("*.json"):
        domain = config_path.stem
        settings_path = rendered_dir/domain/"settings.yaml"
        source_mtime = max(config_path.stat().st_mtime, template_mtime)

        if settings_path.exists() and settings_path.stat().st_mtime >= source_mtime:
            print(f"[skip] {domain}: up to date")
            continue

        PromptTemplate(domain).render()     # 도메인별 인스턴스 생성하면서 렌더링


if __name__ == "__main__":
    render_all_prompts()