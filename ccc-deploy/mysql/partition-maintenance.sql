-- Keeps monthly partitions of `events` ahead of time (I-CCC-27), for a table partitioned by
-- partition-events.sql. Safe to run again; run it once after partition-events.sql:
--   docker compose exec -T mysql sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot xephyguard' < mysql/partition-maintenance.sql
-- xg_extend_event_partitions(n) splits `pmax` until there is a partition for every month up to n months
-- after the current one, so new events never pile up in `pmax` and DROP PARTITION retention keeps working.
-- The monthly event runs it with n = 3 (MySQL 8.4 runs events: event_scheduler is ON by default).
-- Partition pYYYY_MM holds the events of that month (VALUES LESS THAN the first day of the next month).

DROP PROCEDURE IF EXISTS xg_extend_event_partitions;
DELIMITER //
CREATE PROCEDURE xg_extend_event_partitions(IN months_ahead INT)
proc: BEGIN
    DECLARE last_bound DATE;
    DECLARE target DATE DEFAULT DATE_ADD(DATE_FORMAT(CURDATE(), '%Y-%m-01'), INTERVAL months_ahead + 1 MONTH);
    SELECT MAX(STR_TO_DATE(REPLACE(PARTITION_DESCRIPTION, '''', ''), '%Y-%m-%d')) INTO last_bound
      FROM information_schema.PARTITIONS
     WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'events' AND PARTITION_NAME <> 'pmax';
    IF last_bound IS NULL THEN   -- not partitioned (partition-events.sql not applied): nothing to do
        LEAVE proc;
    END IF;
    WHILE last_bound < target DO
        SET @xg_sql = CONCAT('ALTER TABLE events REORGANIZE PARTITION pmax INTO (PARTITION p',
            DATE_FORMAT(last_bound, '%Y_%m'), ' VALUES LESS THAN (''', DATE_ADD(last_bound, INTERVAL 1 MONTH),
            '''), PARTITION pmax VALUES LESS THAN (MAXVALUE))');
        PREPARE xg_stmt FROM @xg_sql;
        EXECUTE xg_stmt;
        DEALLOCATE PREPARE xg_stmt;
        SET last_bound = DATE_ADD(last_bound, INTERVAL 1 MONTH);
    END WHILE;
END //
DELIMITER ;

DROP EVENT IF EXISTS xg_extend_event_partitions_monthly;
CREATE EVENT xg_extend_event_partitions_monthly
    ON SCHEDULE EVERY 1 MONTH STARTS (CURRENT_DATE + INTERVAL 1 DAY)
    DO CALL xg_extend_event_partitions(3);

CALL xg_extend_event_partitions(3);
