-- =============================================================================
-- Social Visualizer DB 스키마
--
-- - 모든 문이 `IF NOT EXISTS` 라서 여러 번 실행해도 안전(idempotent).
--   이미 존재하는 테이블은 통째로 건너뛰므로, 기존 테이블 구조·데이터는 절대 바뀌지 않는다.
--   (제약조건 이름·컬럼 주석 등은 "새 DB에 처음 설치"할 때만 반영된다.)
-- - mail_keyword, processed_attachments, 그리고 메신저 테이블 7개(message_mood 제외)는
--   앱 시작 시 자동 생성된다. message_mood 는 자동 생성되지 않으므로 이 파일 실행이 필요하다.
--
-- 실행:
--   mysql -u root -p < db/schema.sql
--   또는 MySQL 콘솔에서:  SOURCE db/schema.sql;
--
-- 완전 초기화가 필요할 때만 아래 줄의 주석을 풀고 실행한다 (주의: 모든 데이터 삭제):
--   DROP DATABASE IF EXISTS social_visualizer_db;
--
-- 검증:  USE social_visualizer_db; SHOW TABLES;   -- 메일 9개 + 메신저 8개 = 총 17개 테이블
--
-- -----------------------------------------------------------------------------
-- 테이블 관계 (A ─< B : A 하나에 B 여러 개, B 가 A 를 FK 로 참조)
--
--   메일:   user ─< mail_account ─< person ─< mail_keyword
--                                 ─< mail_folder ─< mail
--                                 ─< mail_summarize
--                                 ─< processed_attachments
--           user ─< query
--
--   메신저: user ─< chatroom ─< chatroom_people ─< chatroom_relationship
--                             ─< message_block ─< participant ─< message_keyword
--                             ─< message_summarize
--                             ─< message_mood
-- =============================================================================

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;   -- 테이블 순서와 무관하게 실행되도록. 파일 끝에서 다시 1.

CREATE DATABASE IF NOT EXISTS social_visualizer_db
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE social_visualizer_db;


-- #############################################################################
-- 메일 (GraphRAG / LightRAG 공용)
-- #############################################################################

-- ----------------------------------------------------------------------------
-- user : 서비스 사용자. 한 사람이 여러 메일 계정을 연결하므로 user 는 보통 1행.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `user` (
    `user_id`   CHAR(36)    NOT NULL,   -- UUID
    CONSTRAINT `PK_USER` PRIMARY KEY (`user_id`)
) ENGINE=InnoDB;

-- ----------------------------------------------------------------------------
-- mail_account : 메일 계정 1회 인덱싱 결과 + 비용/토큰 통계.
--                재인덱싱마다 index_date 가 다른 새 행이 쌓인다(버전 개념).
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `mail_account` (
    `user_mail_account_id`  VARCHAR(255)    NOT NULL,   -- 메일 주소
    `index_date`            DATETIME        NOT NULL,   -- 인덱싱 실행 시각 (복합 PK)
    `user_id`               CHAR(36)        NOT NULL,
    `mail_platform`         TEXT            NULL,
    `mail_count`            INT             NULL,
    `index_time`            VARCHAR(50)     NOT NULL,    -- 인덱싱 소요 시간(문자열)
    `llm_model`             VARCHAR(100)    NULL,
    `llm_calls`             INT             NULL,
    `input_tokens`          INT             NULL,
    `output_tokens`         INT             NULL,
    `embed_model`           VARCHAR(100)    NULL,
    `embed_calls`           INT             NULL,
    `embed_tokens`          INT             NULL,
    `total_tokens`          INT             NULL,
    `cost_usd`              DECIMAL(10, 6)  NULL,
    `node_count`            INT             NULL,        -- 그래프 노드 수
    `edge_count`            INT             NULL,        -- 그래프 엣지 수
    CONSTRAINT `PK_MAIL_ACCOUNT` PRIMARY KEY (`user_mail_account_id`, `index_date`),
    CONSTRAINT `FK_user_TO_mail_account`
        FOREIGN KEY (`user_id`) REFERENCES `user` (`user_id`)
) ENGINE=InnoDB;

-- ----------------------------------------------------------------------------
-- person : 메일을 주고받은 상대. LLM 이 생성한 프로필(description)과 관계 라벨 포함.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `person` (
    `person_mail_account_id`    VARCHAR(255)    NOT NULL,   -- 상대 메일 주소
    `user_mail_account_id`      VARCHAR(255)    NOT NULL,
    `index_date`                DATETIME        NOT NULL,
    `person_name`               TEXT            NULL,
    `receive_mails`             INT             NULL,
    `send_mails`                INT             NULL,
    `friendly_mails`            INT             NULL,
    `description`               TEXT            NULL,       -- LLM 생성 프로필
    `relation_label`            VARCHAR(20)     NULL,       -- 가족/연인/친구/동료/사제/지인/기업 등
    `short_bio`                 TEXT            NULL,
    CONSTRAINT `PK_PERSON` PRIMARY KEY (
        `user_mail_account_id`, `index_date`, `person_mail_account_id`
    ),
    CONSTRAINT `FK_mail_account_TO_person`
        FOREIGN KEY (`user_mail_account_id`, `index_date`)
        REFERENCES `mail_account` (`user_mail_account_id`, `index_date`)
) ENGINE=InnoDB;

-- ----------------------------------------------------------------------------
-- mail_folder : 메일함(폴더)별 메일 수.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `mail_folder` (
    `mail_folder_name`      VARCHAR(255)    NOT NULL,
    `user_mail_account_id`  VARCHAR(255)    NOT NULL,
    `index_date`            DATETIME        NOT NULL,
    `mail_count`            INT             NULL,
    CONSTRAINT `PK_MAIL_FOLDER` PRIMARY KEY (
        `user_mail_account_id`, `index_date`, `mail_folder_name`
    ),
    CONSTRAINT `FK_mail_account_TO_mail_folder`
        FOREIGN KEY (`user_mail_account_id`, `index_date`)
        REFERENCES `mail_account` (`user_mail_account_id`, `index_date`)
) ENGINE=InnoDB;

-- ----------------------------------------------------------------------------
-- mail : 개별 메일 1건. 답장 관계(reply_to_mail_id, 응답 소요 시간)까지 계산해 저장.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `mail` (
    `mail_id`               VARCHAR(255)    NOT NULL,
    `user_mail_account_id`  VARCHAR(255)    NOT NULL,
    `index_date`            DATETIME        NOT NULL,
    `mail_folder_name`      VARCHAR(255)    NOT NULL,
    `mail_date`             DATETIME        NULL,
    `sender`                TEXT            NULL,
    `receiver`              TEXT            NULL,
    `direction`             ENUM('sent', 'received')                                            NULL,
    `kg_tone`               ENUM('formal', 'casual', 'transactional', 'notification', 'alert')  NULL,  -- 규칙 기반 분류
    `llm_tone`              ENUM('friendly', 'not_friendly')                                    NULL,  -- LLM 분류
    `is_reply`              INT             NULL,       -- 0/1
    `reply_to_mail_id`      TEXT            NULL,       -- 이 메일이 답장한 원본 mail_id
    `reply_elapsed_hours`   FLOAT           NULL,       -- 원본 수신 → 답장까지 걸린 시간
    CONSTRAINT `PK_MAIL` PRIMARY KEY (`user_mail_account_id`, `index_date`, `mail_id`),
    CONSTRAINT `FK_mail_folder_TO_mail`
        FOREIGN KEY (`user_mail_account_id`, `index_date`, `mail_folder_name`)
        REFERENCES `mail_folder` (`user_mail_account_id`, `index_date`, `mail_folder_name`)
) ENGINE=InnoDB;

-- ----------------------------------------------------------------------------
-- mail_summarize : 연/월 단위 메일 요약 + 주요 연락처(contacts JSON).
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `mail_summarize` (
    `user_mail_account_id`  VARCHAR(255)    NOT NULL,
    `index_date`            DATETIME        NOT NULL,
    `summarize_unit`        ENUM('yearly', 'monthly')   NOT NULL,
    `summary_period`        VARCHAR(10)     NOT NULL,   -- 'YYYY' 또는 'YYYY-MM'
    `summarized_context`    TEXT            NULL,
    `contacts`              JSON            NULL,
    CONSTRAINT `PK_MAIL_SUMMARIZE` PRIMARY KEY (
        `user_mail_account_id`, `index_date`, `summarize_unit`, `summary_period`
    ),
    CONSTRAINT `FK_mail_account_TO_mail_summarize`
        FOREIGN KEY (`user_mail_account_id`, `index_date`)
        REFERENCES `mail_account` (`user_mail_account_id`, `index_date`)
) ENGINE=InnoDB;

-- ----------------------------------------------------------------------------
-- mail_keyword : 사람-키워드-날짜별 언급 횟수.
--                앱(db_writer.init_mail_keyword_table)도 동일 정의로 자동 생성한다.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `mail_keyword` (
    `keyword_name`              VARCHAR(100)    NOT NULL,
    `user_mail_account_id`      VARCHAR(255)    NOT NULL,
    `index_date`                DATETIME        NOT NULL,
    `person_mail_account_id`    VARCHAR(255)    NOT NULL,
    `mail_date`                 DATETIME        NOT NULL,
    `daily_count`               INT             NOT NULL DEFAULT 0,
    CONSTRAINT `PK_MAIL_KEYWORD` PRIMARY KEY (
        `user_mail_account_id`, `index_date`, `person_mail_account_id`,
        `keyword_name`, `mail_date`
    ),
    -- person 이 이미 mail_account 를 참조하므로 mail_account 로의 별도 FK 는 두지 않음(코드와 동일).
    CONSTRAINT `FK_person_TO_mail_keyword`
        FOREIGN KEY (`user_mail_account_id`, `index_date`, `person_mail_account_id`)
        REFERENCES `person` (`user_mail_account_id`, `index_date`, `person_mail_account_id`)
) ENGINE=InnoDB;

-- ----------------------------------------------------------------------------
-- query : 사용자 질의 1건 + 응답/비용/참조 계정 기록.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `query` (
    `query_id`          CHAR(36)        NOT NULL,   -- UUID
    `user_id`           CHAR(36)        NOT NULL,
    `context`           TEXT            NULL,       -- 질문 원문
    `response_date`     DATETIME        NULL,
    `response_time`     DECIMAL(10, 5)  NULL,       -- 응답 소요 시간(초)
    `scope`             ENUM('local', 'global', 'other')    NULL,
    `model_name`        VARCHAR(100)    NULL,
    `input_tokens`      INT             NULL,
    `output_tokens`     INT             NULL,
    `cost_usd`          DECIMAL(10, 5)  NULL,
    `answer`            TEXT            NULL,
    `refer_kg`          JSON            NULL,       -- 답변이 실제 참조한 메일 계정 목록
    CONSTRAINT `PK_QUERY` PRIMARY KEY (`query_id`),
    CONSTRAINT `FK_user_TO_query`
        FOREIGN KEY (`user_id`) REFERENCES `user` (`user_id`)
) ENGINE=InnoDB;

-- ----------------------------------------------------------------------------
-- processed_attachments : 이미 처리한 첨부파일 이력(중복 처리 방지).
--                         앱(db_writer.init_processed_attachments_table)도 동일 정의로 자동 생성.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `processed_attachments` (
    `id`                    INT             NOT NULL AUTO_INCREMENT,
    `user_mail_account_id`  VARCHAR(255)    NOT NULL,
    `index_date`            DATETIME        NOT NULL,
    `mail_id`               VARCHAR(255)    NOT NULL,
    `filename`              VARCHAR(255)    NOT NULL,
    `processed_at`          DATETIME        NOT NULL,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uq_att` (`user_mail_account_id`, `index_date`, `mail_id`, `filename`),
    FOREIGN KEY (`user_mail_account_id`, `index_date`)
        REFERENCES `mail_account` (`user_mail_account_id`, `index_date`)
) ENGINE=InnoDB;


-- #############################################################################
-- 메신저 (카카오톡 등)
--
-- 이 섹션의 8개 테이블은 앱(chatroom_db_writer.init_chatroom_tables)이 서버 시작 시
-- 자동 생성한다. 여기 정의는 그 코드와 1:1로 일치시킨 것이며, 제약조건이 익명
-- (CONSTRAINT 이름 없음)인 것도 코드와 맞추기 위함이다. message_mood 만 코드가
-- 자동 생성하지 않으므로, 이 파일을 실행해야 채워진다.
-- #############################################################################

-- ----------------------------------------------------------------------------
-- chatroom : 채팅방 1회 인덱싱 결과 + 비용/토큰 통계.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `chatroom` (
    `chatroom_id`       CHAR(40)        NOT NULL,   -- build_room_id() 의 SHA1 hex (40자 고정)
    `index_date`        DATETIME        NOT NULL,
    `user_id`           CHAR(36)        NOT NULL,
    `chatroom_name`     VARCHAR(255)    NOT NULL,   -- 표시용 원본 방 이름 (chatroom_id 는 해시라 못 읽음)
    `message_platform`  VARCHAR(50)     NULL,
    `message_count`     INT             NULL,
    `index_time`        VARCHAR(50)     NULL,
    `llm_model`         VARCHAR(100)    NULL,
    `embed_model`       VARCHAR(100)    NULL,
    `llm_calls`         INT             NULL,
    `input_tokens`      INT             NULL,
    `output_tokens`     INT             NULL,
    `embed_calls`       INT             NULL,
    `embed_tokens`      INT             NULL,
    `total_tokens`      INT             NULL,
    `cost_usd`          DECIMAL(12, 6)  NULL,
    `node_count`        INT             NULL,
    `edge_count`        INT             NULL,
    PRIMARY KEY (`chatroom_id`, `index_date`, `user_id`),
    FOREIGN KEY (`user_id`) REFERENCES `user` (`user_id`)
) ENGINE=InnoDB;

-- ----------------------------------------------------------------------------
-- chatroom_people : 채팅방에서 한 번이라도 메시지를 보낸 사람.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `chatroom_people` (
    `participant_id`        VARCHAR(255)    NOT NULL,
    `chatroom_id`           CHAR(40)        NOT NULL,
    `index_date`            DATETIME        NOT NULL,
    `user_id`               CHAR(36)        NOT NULL,
    `chatroom_people_name`  VARCHAR(255)    NULL,
    `message_count`         INT             NULL,
    `description`           TEXT            NULL,
    `short_bio`             TEXT            NULL,
    PRIMARY KEY (`participant_id`, `chatroom_id`, `index_date`, `user_id`),
    FOREIGN KEY (`chatroom_id`, `index_date`, `user_id`)
        REFERENCES `chatroom` (`chatroom_id`, `index_date`, `user_id`)
) ENGINE=InnoDB;

-- ----------------------------------------------------------------------------
-- message_block : 하루치 대화 묶음.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `message_block` (
    `block_id`           VARCHAR(255)    NOT NULL,
    `chatroom_id`        CHAR(40)        NOT NULL,
    `index_date`         DATETIME        NOT NULL,
    `user_id`            CHAR(36)        NOT NULL,
    `block_date`         DATE            NULL,
    `message_count`      INT             NULL,
    `participant_count`  INT             NULL,
    `kg_tone`            VARCHAR(20)     NULL,
    `llm_tone`           VARCHAR(20)     NULL,
    `participant`        JSON            NULL,
    PRIMARY KEY (`block_id`, `chatroom_id`, `index_date`, `user_id`),
    FOREIGN KEY (`chatroom_id`, `index_date`, `user_id`)
        REFERENCES `chatroom` (`chatroom_id`, `index_date`, `user_id`)
) ENGINE=InnoDB;

-- ----------------------------------------------------------------------------
-- participant : 하루(block) 동안 실제로 대화한 사람.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `participant` (
    `participant_name`  VARCHAR(255)    NOT NULL,
    `block_id`          VARCHAR(255)    NOT NULL,
    `chatroom_id`       CHAR(40)        NOT NULL,
    `index_date`        DATETIME        NOT NULL,
    `user_id`           CHAR(36)        NOT NULL,
    `sent_message`      INT             NULL,
    PRIMARY KEY (`participant_name`, `block_id`, `chatroom_id`, `index_date`, `user_id`),
    FOREIGN KEY (`block_id`, `chatroom_id`, `index_date`, `user_id`)
        REFERENCES `message_block` (`block_id`, `chatroom_id`, `index_date`, `user_id`)
) ENGINE=InnoDB;

-- ----------------------------------------------------------------------------
-- message_keyword : 하루(block) 사람별 키워드 언급 횟수.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `message_keyword` (
    `keyword_name`      VARCHAR(100)    NOT NULL,
    `participant_name`  VARCHAR(255)    NOT NULL,
    `block_id`          VARCHAR(255)    NOT NULL,
    `chatroom_id`       CHAR(40)        NOT NULL,
    `index_date`        DATETIME        NOT NULL,
    `user_id`           CHAR(36)        NOT NULL,
    `mention_count`     INT             NULL,
    PRIMARY KEY (`keyword_name`, `participant_name`, `block_id`, `chatroom_id`, `index_date`, `user_id`),
    FOREIGN KEY (`participant_name`, `block_id`, `chatroom_id`, `index_date`, `user_id`)
        REFERENCES `participant` (`participant_name`, `block_id`, `chatroom_id`, `index_date`, `user_id`)
) ENGINE=InnoDB;

-- ----------------------------------------------------------------------------
-- message_summarize : 연/월 단위 채팅방 요약.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `message_summarize` (
    `summarize_unit`        VARCHAR(20)     NOT NULL,
    `summary_period`        VARCHAR(20)     NOT NULL,
    `chatroom_id`           CHAR(40)        NOT NULL,
    `index_date`            DATETIME        NOT NULL,
    `user_id`               CHAR(36)        NOT NULL,
    `summarized_context`    TEXT            NULL,
    `contacts`              JSON            NULL,
    PRIMARY KEY (`summarize_unit`, `summary_period`, `chatroom_id`, `index_date`, `user_id`),
    FOREIGN KEY (`chatroom_id`, `index_date`, `user_id`)
        REFERENCES `chatroom` (`chatroom_id`, `index_date`, `user_id`)
) ENGINE=InnoDB;

-- ----------------------------------------------------------------------------
-- chatroom_relationship : 채팅방 내 사람-사람 관계(가족/연인/…).
--                         person_a/person_b 는 chatroom_people.participant_id 를 참조.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `chatroom_relationship` (
    `chatroom_id`       CHAR(40)        NOT NULL,
    `index_date`        DATETIME        NOT NULL,
    `user_id`           CHAR(36)        NOT NULL,
    `person_a`          VARCHAR(255)    NOT NULL,
    `person_b`          VARCHAR(255)    NOT NULL,
    `relation_label`    VARCHAR(100)    NULL,
    `description`       TEXT            NULL,
    PRIMARY KEY (`chatroom_id`, `index_date`, `user_id`, `person_a`, `person_b`),
    FOREIGN KEY (`person_a`, `chatroom_id`, `index_date`, `user_id`)
        REFERENCES `chatroom_people` (`participant_id`, `chatroom_id`, `index_date`, `user_id`),
    FOREIGN KEY (`person_b`, `chatroom_id`, `index_date`, `user_id`)
        REFERENCES `chatroom_people` (`participant_id`, `chatroom_id`, `index_date`, `user_id`)
) ENGINE=InnoDB;

-- ----------------------------------------------------------------------------
-- message_mood : 연/월별 대화 분위기 점수 + 설명.
--   ※ summary_unit 컬럼명은 의도된 것 (mail_summarize 의 summarize_unit 과 철자가 다름 —
--     앱 코드가 이 이름을 사용).
--   ※ 앱 코드는 이 테이블을 자동 생성하지 않으므로 이 파일 실행이 필수.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `message_mood` (
    `summary_period`    VARCHAR(20)     NOT NULL,
    `summary_unit`      VARCHAR(20)     NOT NULL,
    `chatroom_id`       CHAR(40)        NOT NULL,
    `index_date`        DATETIME        NOT NULL,
    `user_id`           CHAR(36)        NOT NULL,
    `mood_description`  TEXT            NULL,
    `mood_score`        DECIMAL(5, 2)   NULL,
    PRIMARY KEY (`summary_period`, `summary_unit`, `chatroom_id`, `index_date`, `user_id`),
    FOREIGN KEY (`chatroom_id`, `index_date`, `user_id`)
        REFERENCES `chatroom` (`chatroom_id`, `index_date`, `user_id`)
) ENGINE=InnoDB;


SET FOREIGN_KEY_CHECKS = 1;

-- 끝. 확인:  SHOW TABLES;
