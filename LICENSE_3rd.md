# 서드파티 라이선스 (Third-Party Licenses)

Social Visualizer 자체 코드는 [MIT License](LICENSE)를 따릅니다. 단, 일부 서드파티 라이브러리는 해당 라이브러리의 개별 라이선스가 적용되며, 세부 내역은 다음과 같습니다.<br>
전체 구성요소 목록 및 용도는 [SBOM](docs/SBOM.csv) 문서를 참고하세요.

---

## ⚠️ 라이선스 유의사항

Social Visualizer를 **재배포·수정 배포**하는 경우 다음 항목을 확인하세요.

| 구성요소 | 내용 |
|---|---|
| **mysql-connector-python 9.6.0** | `GPL-2.0` 이나 **FOSS License Exception**이 포함되어 MIT 등 다른 FOSS 라이선스 프로젝트와 함께 사용 가능. pip 의존성으로 설치만 하고 재배포하지 않음. 카피레프트가 부담되면 `PyMySQL`(MIT)로 대체 가능 |
| **LightRAG (lightrag-hku) 1.5.6** | `MIT`. pip이 아니라 **git clone으로 프로젝트 루트에 소스 포함**(README 안내 방식). 재배포 시 LightRAG의 LICENSE 파일을 함께 유지해야 함 |
| **Azure SDK 계열** (`azure-common`, `azure-core`, `azure-cosmos`, `azure-identity`, `azure-search-documents`, `azure-storage-blob`, `msal`, `msal-extensions`) | `graphrag`의 선택적 스토리지 백엔드 의존성으로 설치되나 **본 프로젝트에서는 미사용** (LanceDB + MySQL 사용). 모두 `MIT` |
| **@fortawesome/fontawesome-free 7.1.0** | 코드 `MIT`, 아이콘 `CC-BY-4.0`, 폰트 `OFL-1.1`. 아이콘 사용 시 Font Awesome 출처 표기 의무 |

---

## Python 패키지

| 구성요소 | 버전 | 라이선스 | 출처 |
|---|---|---|---|
| aiofiles | 25.1.0 | Apache-2.0 | https://github.com/Tinche/aiofiles |
| aiohappyeyeballs | 2.7.1 | PSF-2.0 | https://github.com/aio-libs/aiohappyeyeballs |
| aiohttp | 3.14.3 | Apache-2.0 AND MIT | https://github.com/aio-libs/aiohttp |
| aiosignal | 1.4.0 | Apache-2.0 | https://github.com/aio-libs/aiosignal |
| annotated-doc | 0.0.4 | MIT | https://github.com/fastapi/annotated-doc |
| annotated-types | 0.7.0 | MIT | https://github.com/annotated-types/annotated-types |
| anyio | 4.12.1 | MIT | https://github.com/agronholm/anyio |
| asttokens | 2.4.1 | Apache-2.0 | https://github.com/gristlabs/asttokens |
| attrs | 26.1.0 | MIT | https://github.com/python-attrs/attrs |
| azure-common | 1.1.28 | MIT | https://github.com/Azure/azure-sdk-for-python |
| azure-core | 1.38.3 | MIT | https://github.com/Azure/azure-sdk-for-python |
| azure-cosmos | 4.15.0 | MIT | https://github.com/Azure/azure-sdk-for-python |
| azure-identity | 1.25.3 | MIT | https://github.com/Azure/azure-sdk-for-python |
| azure-search-documents | 12.0.0 | MIT | https://github.com/Azure/azure-sdk-for-python |
| azure-storage-blob | 12.28.0 | MIT | https://github.com/Azure/azure-sdk-for-python |
| beautifulsoup4 | 4.15.0 | MIT | https://www.crummy.com/software/BeautifulSoup/ |
| blinker | 1.9.0 | MIT | https://github.com/pallets-eco/blinker |
| blis | 1.3.3 | BSD-3-Clause | https://github.com/explosion/cython-blis |
| catalogue | 2.0.10 | MIT | https://github.com/explosion/catalogue |
| certifi | 2026.2.25 | MPL-2.0 | https://github.com/certifi/python-certifi |
| cffi | 2.0.0 | MIT | https://github.com/python-cffi/cffi |
| charset-normalizer | 3.4.6 | MIT | https://github.com/jawah/charset_normalizer |
| click | 8.4.2 | BSD-3-Clause | https://github.com/pallets/click |
| cloudpathlib | 0.23.0 | MIT | https://github.com/drivendataorg/cloudpathlib |
| colorama | 0.4.6 | BSD-3-Clause | https://github.com/tartley/colorama |
| coloredlogs | 15.0.1 | MIT | https://github.com/xolox/python-coloredlogs |
| confection | 0.1.5 | MIT | https://github.com/explosion/confection |
| configparser | 7.2.0 | MIT | https://github.com/jaraco/configparser |
| contourpy | 1.3.3 | BSD-3-Clause | https://github.com/contourpy/contourpy |
| cryptography | 46.0.5 | Apache-2.0 OR BSD-3-Clause | https://github.com/pyca/cryptography |
| cycler | 0.12.1 | BSD-3-Clause | https://github.com/matplotlib/cycler |
| cymem | 2.0.13 | MIT | https://github.com/explosion/cymem |
| defusedxml | 0.7.1 | PSF-2.0 | https://github.com/tiran/defusedxml |
| deprecation | 2.1.0 | Apache-2.0 | https://github.com/briancurtin/deprecation |
| devtools | 0.12.2 | MIT | https://github.com/pydantic/python-devtools |
| distro | 1.9.0 | Apache-2.0 | https://github.com/python-distro/distro |
| environs | 11.2.1 | MIT | https://github.com/sloria/environs |
| et_xmlfile | 2.0.0 | MIT | https://pypi.org/project/et-xmlfile/ |
| executing | 2.2.1 | MIT | https://github.com/alexmojaki/executing |
| fastapi | 0.141.1 | MIT | https://github.com/fastapi/fastapi |
| fastuuid | 0.14.0 | BSD-3-Clause | https://github.com/thusoy/fastuuid |
| filelock | 3.32.2 | Unlicense | https://github.com/tox-dev/py-filelock |
| Flask | 3.1.3 | BSD-3-Clause | https://github.com/pallets/flask |
| flask-cors | 6.0.2 | MIT | https://github.com/corydolphin/flask-cors |
| flatbuffers | 25.12.19 | Apache-2.0 | https://github.com/google/flatbuffers |
| fonttools | 4.62.1 | MIT | https://github.com/fonttools/fonttools |
| frozenlist | 1.8.0 | Apache-2.0 | https://github.com/aio-libs/frozenlist |
| fsspec | 2026.7.0 | BSD-3-Clause | https://github.com/fsspec/filesystem_spec |
| future | 1.0.0 | MIT | https://github.com/PythonCharmers/python-future |
| google-api-core | 2.30.3 | Apache-2.0 | https://github.com/googleapis/python-api-core |
| google-genai | 2.2.0 | Apache-2.0 | https://github.com/googleapis/python-genai |
| graphrag | 3.1.1 | MIT | https://github.com/microsoft/graphrag |
| graphrag-cache | 3.1.1 | MIT | https://github.com/microsoft/graphrag |
| graphrag-chunking | 3.1.1 | MIT | https://github.com/microsoft/graphrag |
| graphrag-common | 3.1.1 | MIT | https://github.com/microsoft/graphrag |
| graphrag-input | 3.1.1 | MIT | https://github.com/microsoft/graphrag |
| graphrag-llm | 3.1.1 | MIT | https://github.com/microsoft/graphrag |
| graphrag-storage | 3.1.1 | MIT | https://github.com/microsoft/graphrag |
| graphrag-vectors | 3.1.1 | MIT | https://github.com/microsoft/graphrag |
| lightrag-hku (LightRAG) | 1.5.6 (git 24ee484, 2026-08-10) | MIT | https://github.com/HKUDS/LightRAG |
| graspologic-native | 1.2.5 | MIT | https://github.com/graspologic-org/graspologic-native |
| h11 | 0.16.0 | MIT | https://github.com/python-hyper/h11 |
| hf-xet | 1.6.0 | Apache-2.0 | https://github.com/huggingface/xet-core |
| httpcore | 1.0.9 | BSD-3-Clause | https://github.com/encode/httpcore |
| httpx | 0.28.1 | BSD-3-Clause | https://github.com/encode/httpx |
| huggingface_hub | 1.27.0 | Apache-2.0 | https://github.com/huggingface/huggingface_hub |
| humanfriendly | 10.0 | MIT | https://github.com/xolox/python-humanfriendly |
| idna | 3.11 | BSD-3-Clause | https://github.com/kjd/idna |
| importlib_metadata | 8.9.0 | Apache-2.0 | https://github.com/python/importlib_metadata |
| isodate | 0.7.2 | BSD-3-Clause | https://github.com/gweis/isodate |
| itsdangerous | 2.2.0 | BSD-3-Clause | https://github.com/pallets/itsdangerous |
| Jinja2 | 3.1.6 | BSD-3-Clause | https://github.com/pallets/jinja |
| jiter | 0.13.0 | MIT | https://github.com/pydantic/jiter |
| joblib | 1.5.3 | BSD-3-Clause | https://github.com/joblib/joblib |
| json_repair | 0.30.3 | MIT | https://github.com/mangiucugna/json_repair |
| jsonschema | 4.26.0 | MIT | https://github.com/python-jsonschema/jsonschema |
| jsonschema-specifications | 2025.9.1 | MIT | https://github.com/python-jsonschema/jsonschema-specifications |
| kiwisolver | 1.5.0 | BSD-3-Clause | https://github.com/nucleic/kiwi |
| lance-namespace | 0.9.0 | Apache-2.0 | https://github.com/lance-format/lance-namespace |
| lance-namespace-urllib3-client | 0.9.0 | Apache-2.0 | https://github.com/lance-format/lance-namespace |
| lancedb | 0.34.0 | Apache-2.0 | https://github.com/lancedb/lancedb |
| litellm | 1.92.0 | MIT | https://github.com/BerriAI/litellm |
| lxml | 6.0.2 | BSD-3-Clause | https://github.com/lxml/lxml |
| magika | 0.6.3 | Apache-2.0 | https://github.com/google/magika |
| markdown-it-py | 4.0.0 | MIT | https://github.com/executablebooks/markdown-it-py |
| markdownify | 1.2.3 | MIT | https://github.com/matthewwithanm/python-markdownify |
| markitdown | 0.1.7 | MIT | https://github.com/microsoft/markitdown |
| MarkupSafe | 3.0.3 | BSD-3-Clause | https://github.com/pallets/markupsafe |
| marshmallow | 4.2.2 | MIT | https://github.com/marshmallow-code/marshmallow |
| matplotlib | 3.10.8 | PSF-2.0 (matplotlib license) | https://github.com/matplotlib/matplotlib |
| mdurl | 0.1.2 | MIT | https://github.com/executablebooks/mdurl |
| mpmath | 1.3.0 | BSD-3-Clause | https://github.com/mpmath/mpmath |
| msal | 1.35.1 | MIT | https://github.com/AzureAD/microsoft-authentication-library-for-python |
| msal-extensions | 1.3.1 | MIT | https://github.com/AzureAD/microsoft-authentication-extensions-for-python |
| multidict | 6.7.1 | Apache-2.0 | https://github.com/aio-libs/multidict |
| murmurhash | 1.0.15 | MIT | https://github.com/explosion/murmurhash |
| mysql-connector-python | 9.6.0 | GPL-2.0-only WITH FOSS-exception | https://github.com/mysql/mysql-connector-python |
| nano-vectordb | 0.0.4.3 | MIT | https://github.com/gusye1234/nano-vectordb |
| nest-asyncio2 | 1.7.2 | BSD-2-Clause | https://github.com/Chaoses-Ib/nest-asyncio2 |
| networkx | 3.6.1 | BSD-3-Clause | https://github.com/networkx/networkx |
| nltk | 3.10.2 | Apache-2.0 | https://github.com/nltk/nltk |
| numpy | 2.4.6 | BSD-3-Clause | https://github.com/numpy/numpy |
| olefile | 0.47 | BSD-2-Clause | https://github.com/decalage2/olefile |
| onnxruntime | 1.20.1 | MIT | https://github.com/microsoft/onnxruntime |
| openai | 2.53.0 | Apache-2.0 | https://github.com/openai/openai-python |
| openpyxl | 3.1.5 | MIT | https://foss.heptapod.net/openpyxl/openpyxl |
| orjson | 3.11.9 | Apache-2.0 OR MIT | https://github.com/ijl/orjson |
| overrides | 7.7.0 | Apache-2.0 | https://github.com/mkorpela/overrides |
| packaging | 26.0 | Apache-2.0 OR BSD-2-Clause | https://github.com/pypa/packaging |
| pandas | 3.0.5 | BSD-3-Clause | https://github.com/pandas-dev/pandas |
| pdfminer.six | 20260107 | MIT | https://github.com/pdfminer/pdfminer.six |
| pdfplumber | 0.11.10 | MIT | https://github.com/jsvine/pdfplumber |
| pillow | 12.2.0 | MIT-CMU | https://github.com/python-pillow/Pillow |
| pipmaster | 1.1.8 | Apache-2.0 | https://github.com/ParisNeo/pipmaster |
| preshed | 3.0.12 | MIT | https://github.com/explosion/preshed |
| propcache | 0.5.2 | Apache-2.0 | https://github.com/aio-libs/propcache |
| protobuf | 7.35.1 | BSD-3-Clause | https://github.com/protocolbuffers/protobuf |
| pyarrow | 25.0.1 | Apache-2.0 | https://github.com/apache/arrow |
| pycparser | 3.0 | BSD-3-Clause | https://github.com/eliben/pycparser |
| pydantic | 2.12.5 | MIT | https://github.com/pydantic/pydantic |
| pydantic-settings | 2.15.0 | MIT | https://github.com/pydantic/pydantic-settings |
| pydantic_core | 2.41.5 | MIT | https://github.com/pydantic/pydantic-core |
| Pygments | 2.19.2 | BSD-2-Clause | https://github.com/pygments/pygments |
| PyJWT | 2.12.1 | MIT | https://github.com/jpadilla/pyjwt |
| pylance | 0.20.0 | Apache-2.0 | https://github.com/lancedb/lance |
| pyparsing | 3.3.2 | MIT | https://github.com/pyparsing/pyparsing |
| pypdfium2 | 5.11.0 | BSD-3-Clause AND Apache-2.0 | https://github.com/pypdfium2-team/pypdfium2 |
| pypinyin | 0.55.0 | MIT | https://github.com/mozillazg/python-pinyin |
| pyreadline3 | 3.5.6 | BSD-3-Clause | https://github.com/pyreadline3/pyreadline3 |
| python-dateutil | 2.9.0.post0 | Apache-2.0 OR BSD-3-Clause | https://github.com/dateutil/dateutil |
| python-docx | 1.2.0 | MIT | https://github.com/python-openxml/python-docx |
| python-dotenv | 1.2.2 | BSD-3-Clause | https://github.com/theskumar/python-dotenv |
| python-pptx | 1.0.2 | MIT | https://github.com/scanny/python-pptx |
| pytz | 2026.1.post1 | MIT | https://github.com/stub42/pytz |
| PyYAML | 6.0.3 | MIT | https://github.com/yaml/pyyaml |
| referencing | 0.37.0 | MIT | https://github.com/python-jsonschema/referencing |
| regex | 2026.2.28 | Apache-2.0 | https://github.com/mrabarnett/mrab-regex |
| requests | 2.32.5 | Apache-2.0 | https://github.com/psf/requests |
| rich | 13.9.4 | MIT | https://github.com/Textualize/rich |
| rpds-py | 2026.6.3 | MIT | https://github.com/crate-py/rpds |
| scipy | 1.17.1 | BSD-3-Clause | https://github.com/scipy/scipy |
| seaborn | 0.13.2 | BSD-3-Clause | https://github.com/mwaskom/seaborn |
| shellingham | 1.5.4 | ISC | https://github.com/sarugaku/shellingham |
| six | 1.17.0 | MIT | https://github.com/benjaminp/six |
| smart_open | 7.5.1 | MIT | https://github.com/piskvorky/smart_open |
| sniffio | 1.3.1 | MIT OR Apache-2.0 | https://github.com/python-trio/sniffio |
| soupsieve | 2.9.2 | MIT | https://github.com/facelessuser/soupsieve |
| spacy | 3.8.11 | MIT | https://github.com/explosion/spaCy |
| spacy-legacy | 3.0.12 | MIT | https://github.com/explosion/spacy-legacy |
| spacy-loggers | 1.0.5 | MIT | https://github.com/explosion/spacy-loggers |
| srsly | 2.5.2 | MIT | https://github.com/explosion/srsly |
| starlette | 1.6.0 | BSD-3-Clause | https://github.com/encode/starlette |
| sympy | 1.14.0 | BSD-3-Clause | https://github.com/sympy/sympy |
| tenacity | 9.1.4 | Apache-2.0 | https://github.com/jd/tenacity |
| textblob | 0.18.0.post0 | MIT | https://github.com/sloria/TextBlob |
| thinc | 8.3.10 | MIT | https://github.com/explosion/thinc |
| tiktoken | 0.12.0 | MIT | https://github.com/openai/tiktoken |
| tokenizers | 0.23.1 | Apache-2.0 | https://github.com/huggingface/tokenizers |
| toml | 0.10.2 | MIT | https://github.com/uiri/toml |
| tqdm | 4.67.3 | MPL-2.0 AND MIT | https://github.com/tqdm/tqdm |
| typer | 0.27.1 | MIT | https://github.com/fastapi/typer |
| typer-slim | 0.21.2 | MIT | https://github.com/fastapi/typer |
| typing-inspection | 0.4.2 | MIT | https://github.com/pydantic/typing-inspection |
| typing_extensions | 4.15.0 | PSF-2.0 | https://github.com/python/typing_extensions |
| tzdata | 2025.3 | Apache-2.0 | https://github.com/python/tzdata |
| urllib3 | 2.6.3 | MIT | https://github.com/urllib3/urllib3 |
| wasabi | 1.1.3 | MIT | https://github.com/explosion/wasabi |
| weasel | 0.4.3 | MIT | https://github.com/explosion/weasel |
| Werkzeug | 3.1.6 | BSD-3-Clause | https://github.com/pallets/werkzeug |
| wrapt | 2.1.2 | BSD-2-Clause | https://github.com/GrahamDumpleton/wrapt |
| xlsxwriter | 3.2.9 | BSD-2-Clause | https://github.com/jmcnamara/XlsxWriter |
| yarl | 1.24.5 | Apache-2.0 | https://github.com/aio-libs/yarl |
| zipp | 4.1.0 | MIT | https://github.com/jaraco/zipp |

## 프론트엔드 — 런타임 의존성

| 구성요소 | 버전 | 라이선스 | 출처 |
|---|---|---|---|
| @fortawesome/fontawesome-free | 7.1.0 | CC-BY-4.0 AND OFL-1.1 AND MIT | https://github.com/FortAwesome/Font-Awesome |
| @popperjs/core | 2.11.8 | MIT | https://github.com/popperjs/popper-core |
| @radix-ui/react-dropdown-menu | 2.1.24 | MIT | https://github.com/radix-ui/primitives |
| bootstrap | 5.3.8 | MIT | https://github.com/twbs/bootstrap |
| bootstrap-icons | 1.13.1 | MIT | https://github.com/twbs/icons |
| cobe | 2.0.1 | MIT | https://github.com/shuding/cobe |
| d3 | 7.9.0 | ISC | https://github.com/d3/d3 |
| dompurify | 3.3.1 | MPL-2.0 OR Apache-2.0 | https://github.com/cure53/DOMPurify |
| i18next | 26.0.3 | MIT | https://github.com/i18next/i18next |
| react | 19.2.8 | MIT | https://github.com/facebook/react |
| react-dom | 19.2.8 | MIT | https://github.com/facebook/react |
| tailwindcss | 4.3.3 | MIT | https://github.com/tailwindlabs/tailwindcss |

## 프론트엔드 — 개발 의존성

| 구성요소 | 버전 | 라이선스 | 출처 |
|---|---|---|---|
| @eslint/js | 9.39.2 | MIT | https://github.com/eslint/eslint |
| @tailwindcss/vite | 4.3.3 | MIT | https://github.com/tailwindlabs/tailwindcss |
| @types/react | 19.2.18 | MIT | https://github.com/DefinitelyTyped/DefinitelyTyped |
| @types/react-dom | 19.2.4 | MIT | https://github.com/DefinitelyTyped/DefinitelyTyped |
| @vitejs/plugin-react | 5.2.0 | MIT | https://github.com/vitejs/vite-plugin-react |
| cross-env | 10.1.0 | MIT | https://github.com/kentcdodds/cross-env |
| eslint | 9.39.2 | MIT | https://github.com/eslint/eslint |
| eslint-config-prettier | 10.1.8 | MIT | https://github.com/prettier/eslint-config-prettier |
| prettier | 3.7.4 | MIT | https://github.com/prettier/prettier |
| rollup-plugin-visualizer | 6.0.5 | MIT | https://github.com/btd/rollup-plugin-visualizer |
| sass | 1.97.2 | MIT | https://github.com/sass/dart-sass |
| terser | 5.44.1 | BSD-2-Clause | https://github.com/terser/terser |
| typescript | 7.0.2 | Apache-2.0 | https://github.com/microsoft/TypeScript |
| vite | 7.3.1 | MIT | https://github.com/vitejs/vite |