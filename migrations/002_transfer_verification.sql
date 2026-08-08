-- İlerleme ve imapsync bütünlük doğrulama alanlarını ekler.
ALTER TABLE jobs
    ADD COLUMN verified TINYINT(1) NOT NULL DEFAULT 0 AFTER progress,
    ADD COLUMN detected_errors INT UNSIGNED NULL AFTER verified;
