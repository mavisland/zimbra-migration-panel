-- Mevcut kurulumları aktif mailbox kilidi yapısına yükseltir.
-- Çalıştırmadan önce veritabanı yedeği alın.

ALTER TABLE jobs
    ADD COLUMN lock_key CHAR(64) NULL AFTER end_date,
    ADD COLUMN active_lock CHAR(64) NULL AFTER lock_key;

UPDATE jobs
SET lock_key = SHA2(CONCAT_WS(CHAR(0), LOWER(source_host), LOWER(source_email),
                             LOWER(target_host), LOWER(target_email)), 256);

UPDATE jobs
SET active_lock = CASE
    WHEN status IN ('queued','starting','running','stopping') THEN lock_key
    ELSE NULL
END;

-- Aynı mailbox için eski veride birden fazla aktif iş varsa yalnızca en eski iş aktif kalır.
UPDATE jobs newer
JOIN jobs older ON newer.active_lock = older.active_lock AND newer.id > older.id
SET newer.status = 'stopped', newer.active_lock = NULL,
    newer.error = 'Şema yükseltmesinde mükerrer aktif iş durduruldu',
    newer.finished_at = UTC_TIMESTAMP(6)
WHERE newer.active_lock IS NOT NULL;

ALTER TABLE jobs
    MODIFY lock_key CHAR(64) NOT NULL,
    ADD UNIQUE INDEX jobs_active_lock_uq (active_lock);
