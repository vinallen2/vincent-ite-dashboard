-- Draft D1 schema for migration. No live records are inserted by this file.
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL CHECK(kind IN ('daily','bonus')),
  session_date TEXT NOT NULL,
  title TEXT NOT NULL,
  teaching TEXT NOT NULL DEFAULT '',
  review_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(kind, session_date)
);
CREATE TABLE IF NOT EXISTS questions (
  session_id TEXT NOT NULL REFERENCES sessions(id),
  question_id TEXT NOT NULL,
  stem TEXT NOT NULL,
  domain TEXT NOT NULL,
  topic TEXT NOT NULL,
  objective TEXT NOT NULL,
  difficulty TEXT NOT NULL CHECK(difficulty IN ('application','integration')),
  level TEXT NOT NULL CHECK(level IN ('basic','advanced')),
  answer TEXT NOT NULL CHECK(answer IN ('A','B','C','D')),
  options_json TEXT NOT NULL,
  sources_json TEXT NOT NULL,
  PRIMARY KEY(session_id,question_id)
);
CREATE TABLE IF NOT EXISTS first_attempts (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL UNIQUE REFERENCES sessions(id),
  submitted_at TEXT NOT NULL,
  completion_date TEXT NOT NULL,
  correct_count INTEGER NOT NULL CHECK(correct_count BETWEEN 0 AND 3),
  total INTEGER NOT NULL DEFAULT 3 CHECK(total=3)
);
CREATE TABLE IF NOT EXISTS attempt_answers (
  attempt_id TEXT NOT NULL REFERENCES first_attempts(id),
  session_id TEXT NOT NULL,
  question_id TEXT NOT NULL,
  choice TEXT NOT NULL CHECK(choice IN ('A','B','C','D')),
  confidence TEXT CHECK(confidence IN ('sure','unsure','guessed') OR confidence IS NULL),
  correct INTEGER NOT NULL CHECK(correct IN (0,1)),
  PRIMARY KEY(attempt_id,question_id),
  FOREIGN KEY(session_id,question_id) REFERENCES questions(session_id,question_id)
);
CREATE TABLE IF NOT EXISTS review_plans (
  id TEXT PRIMARY KEY,
  topic TEXT NOT NULL,
  due_date TEXT,
  reason TEXT NOT NULL DEFAULT '',
  method TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'Planned',
  last_evidence TEXT,
  next_step TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS articles (
  id TEXT PRIMARY KEY,
  session_date TEXT,
  title TEXT NOT NULL,
  normalized_title TEXT NOT NULL UNIQUE,
  authors TEXT NOT NULL,
  journal TEXT NOT NULL,
  year INTEGER NOT NULL,
  doi TEXT,
  url TEXT NOT NULL,
  topic TEXT NOT NULL,
  takeaway TEXT NOT NULL,
  status TEXT NOT NULL,
  UNIQUE(doi)
);
CREATE TABLE IF NOT EXISTS delivery_records (
  session_id TEXT PRIMARY KEY REFERENCES sessions(id),
  gmail_message_id TEXT NOT NULL UNIQUE,
  sent_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reviews_due ON review_plans(due_date,status);
CREATE INDEX IF NOT EXISTS idx_attempt_completion ON first_attempts(completion_date);
