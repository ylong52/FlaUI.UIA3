-- survey_ai_agent：与 survey_bg_manage 共用同一个数据库。
-- 表名统一使用 ai_agent_* 前缀，与现有业务表隔离；全部幂等。

CREATE TABLE IF NOT EXISTS ai_agent_tasks (
  task_id       VARCHAR(128) NOT NULL,
  created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (task_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS ai_agent_pages (
  id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  task_id        VARCHAR(128) NOT NULL,
  page_id        VARCHAR(128) NOT NULL,
  html_sha256    CHAR(64)     NOT NULL,
  questions_json JSON         NOT NULL,
  plan_json      JSON         NOT NULL,
  page_status    VARCHAR(16)  NOT NULL DEFAULT 'partial',
  created_at     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_ai_agent_page (task_id, page_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS ai_agent_answers (
  id                    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  task_id               VARCHAR(128) NOT NULL,
  page_id               VARCHAR(128) NOT NULL,
  question_id           VARCHAR(128) NOT NULL,
  fingerprint           CHAR(64)     NOT NULL DEFAULT '',
  question_type         VARCHAR(32)  NOT NULL,
  selected_options_json JSON         NULL,
  answer_text           MEDIUMTEXT   NULL,
  matrix_json           JSON         NULL,
  ranking_json          JSON         NULL,
  numeric_value         DECIMAL(20,6) NULL,
  status                VARCHAR(16)  NOT NULL,
  source                VARCHAR(32)  NULL,
  confidence            DECIMAL(4,3) NULL,
  notes                 VARCHAR(1000) NULL,
  updated_at            DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_ai_agent_answer (task_id, page_id, question_id),
  KEY idx_ai_agent_answer_fp (task_id, fingerprint),
  KEY idx_ai_agent_answer_page (task_id, page_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS ai_agent_context (
  task_id      VARCHAR(128) NOT NULL,
  context_json JSON         NOT NULL,
  updated_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (task_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS ai_agent_llm_usage (
  id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  task_id           VARCHAR(128) NOT NULL,
  page_id           VARCHAR(128) NOT NULL,
  model             VARCHAR(128) NULL,
  prompt_tokens     INT NOT NULL DEFAULT 0,
  completion_tokens INT NOT NULL DEFAULT 0,
  total_tokens      INT NOT NULL DEFAULT 0,
  created_at        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_ai_agent_usage_task (task_id),
  KEY idx_ai_agent_usage_page (task_id, page_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
