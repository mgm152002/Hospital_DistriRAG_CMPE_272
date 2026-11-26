-- A person can rename a conversation; without a title the list shows its first (redacted) question.
ALTER TABLE conversations ADD COLUMN title text CHECK (title IS NULL OR char_length(title) BETWEEN 1 AND 80);
