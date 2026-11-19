-- Production-compatible schema; no study records or credentials.
CREATE TABLE `study_articles` (
	`id` text PRIMARY KEY NOT NULL,
	`date` text NOT NULL,
	`title` text NOT NULL,
	`title_key` text NOT NULL,
	`authors` text NOT NULL,
	`journal` text NOT NULL,
	`year` text NOT NULL,
	`doi` text,
	`url` text NOT NULL,
	`topic` text NOT NULL,
	`takeaway` text NOT NULL,
	`status` text NOT NULL
);

CREATE UNIQUE INDEX `article_title_unique` ON `study_articles` (`title_key`);
CREATE UNIQUE INDEX `article_doi_unique` ON `study_articles` (`doi`);
CREATE TABLE `study_attempts` (
	`id` text PRIMARY KEY NOT NULL,
	`session_id` text NOT NULL,
	`answers` text NOT NULL,
	`result` text NOT NULL,
	`submitted_at` text NOT NULL,
	`sync_status` text DEFAULT 'pending' NOT NULL,
	`sync_receipt` text,
	FOREIGN KEY (`session_id`) REFERENCES `study_sessions`(`id`) ON UPDATE no action ON DELETE no action
);

CREATE UNIQUE INDEX `one_first_attempt_per_session` ON `study_attempts` (`session_id`);
CREATE TABLE `study_reviews` (
	`id` text PRIMARY KEY NOT NULL,
	`topic` text NOT NULL,
	`due_date` text,
	`reason` text NOT NULL,
	`method` text NOT NULL,
	`status` text NOT NULL,
	`last_evidence` text,
	`next_step` text NOT NULL
);

CREATE TABLE `study_sessions` (
	`id` text PRIMARY KEY NOT NULL,
	`date` text NOT NULL,
	`payload` text NOT NULL,
	`created_at` text NOT NULL
);

CREATE INDEX `study_session_date` ON `study_sessions` (`date`);
CREATE TABLE `study_state` (
	`key` text PRIMARY KEY NOT NULL,
	`value` text NOT NULL,
	`updated_at` text NOT NULL
);
