CREATE TABLE parents (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0)
) STRICT;

CREATE TABLE students (
    id INTEGER PRIMARY KEY,
    parent_id INTEGER NOT NULL REFERENCES parents(id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0)
) STRICT;

CREATE TABLE trial_classes (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    starts_at TEXT NOT NULL
) STRICT;

CREATE TABLE bookings (
    id INTEGER PRIMARY KEY,
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    trial_class_id INTEGER NOT NULL REFERENCES trial_classes(id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    status TEXT NOT NULL DEFAULT 'pending_payment',
    status_reason TEXT,
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (
        (status IN ('pending_payment', 'confirmed', 'payment_failed') AND status_reason IS NULL)
        OR (status = 'cancelled' AND status_reason IS NOT NULL
            AND status_reason IN ('class_full', 'duplicate_booking'))
    )
) STRICT;

CREATE TABLE payment_attempts (
    id INTEGER PRIMARY KEY,
    booking_id INTEGER NOT NULL REFERENCES bookings(id) ON DELETE RESTRICT ON UPDATE RESTRICT,
    requested_outcome TEXT NOT NULL CHECK (requested_outcome IN ('success', 'failure')),
    outcome TEXT NOT NULL DEFAULT 'pending',
    reason TEXT,
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    CHECK (
        (outcome = 'pending' AND reason IS NULL)
        OR (outcome = 'succeeded' AND requested_outcome = 'success' AND reason IS NULL)
        OR (outcome = 'failed' AND requested_outcome = 'failure'
            AND reason IS NOT NULL AND reason = 'mock_declined')
        OR (outcome = 'blocked' AND requested_outcome = 'success'
            AND reason IS NOT NULL AND reason IN ('class_full', 'duplicate_booking'))
    )
) STRICT;

CREATE UNIQUE INDEX confirmed_child_class ON bookings(trial_class_id, student_id)
WHERE status = 'confirmed';
CREATE UNIQUE INDEX succeeded_booking ON payment_attempts(booking_id)
WHERE outcome = 'succeeded';

CREATE TRIGGER booking_insert_pending BEFORE INSERT ON bookings
WHEN NEW.status != 'pending_payment'
BEGIN SELECT RAISE(ABORT, 'booking_must_start_pending'); END;

CREATE TRIGGER booking_update_guard BEFORE UPDATE ON bookings
BEGIN
    SELECT CASE WHEN OLD.status != 'pending_payment' OR NEW.status = 'pending_payment'
        OR NEW.id IS NOT OLD.id OR NEW.student_id IS NOT OLD.student_id
        OR NEW.trial_class_id IS NOT OLD.trial_class_id
        OR NEW.idempotency_key IS NOT OLD.idempotency_key
        OR NEW.created_at IS NOT OLD.created_at
        THEN RAISE(ABORT, 'immutable_booking') END;
    SELECT CASE WHEN NEW.status = 'confirmed' AND NOT EXISTS (
        SELECT 1 FROM payment_attempts WHERE booking_id = OLD.id AND outcome = 'succeeded'
    ) THEN RAISE(ABORT, 'successful_payment_required') END;
    SELECT CASE WHEN NEW.status = 'confirmed' AND EXISTS (
        SELECT 1 FROM bookings WHERE trial_class_id = NEW.trial_class_id
        AND student_id = NEW.student_id AND status = 'confirmed' AND id != OLD.id
    ) THEN RAISE(ABORT, 'duplicate_booking') END;
    SELECT CASE WHEN NEW.status = 'confirmed' AND (
        SELECT count(*) FROM bookings WHERE trial_class_id = NEW.trial_class_id
        AND status = 'confirmed' AND id != OLD.id
    ) >= 4 THEN RAISE(ABORT, 'class_full') END;
    SELECT CASE WHEN NEW.status = 'payment_failed' AND NOT EXISTS (
        SELECT 1 FROM payment_attempts WHERE booking_id = OLD.id AND outcome = 'failed'
    ) THEN RAISE(ABORT, 'failed_payment_required') END;
    SELECT CASE WHEN NEW.status = 'cancelled' AND NOT EXISTS (
        SELECT 1 FROM payment_attempts WHERE booking_id = OLD.id
        AND outcome = 'blocked' AND reason = NEW.status_reason
    ) THEN RAISE(ABORT, 'blocked_payment_required') END;
END;

CREATE TRIGGER booking_delete_guard BEFORE DELETE ON bookings
WHEN OLD.status != 'pending_payment'
BEGIN SELECT RAISE(ABORT, 'immutable_booking'); END;

CREATE TRIGGER attempt_insert_pending BEFORE INSERT ON payment_attempts
WHEN NEW.outcome != 'pending'
    OR (SELECT status FROM bookings WHERE id = NEW.booking_id) != 'pending_payment'
BEGIN SELECT RAISE(ABORT, 'attempt_must_start_pending'); END;

CREATE TRIGGER attempt_update_guard BEFORE UPDATE ON payment_attempts
WHEN OLD.outcome != 'pending' OR NEW.outcome = 'pending'
    OR NEW.id IS NOT OLD.id OR NEW.booking_id IS NOT OLD.booking_id
    OR NEW.requested_outcome IS NOT OLD.requested_outcome
    OR NEW.idempotency_key IS NOT OLD.idempotency_key
    OR NEW.created_at IS NOT OLD.created_at
    OR (SELECT status FROM bookings WHERE id = OLD.booking_id) != 'pending_payment'
BEGIN SELECT RAISE(ABORT, 'immutable_attempt'); END;

CREATE TRIGGER attempt_delete_guard BEFORE DELETE ON payment_attempts
WHEN OLD.outcome != 'pending'
BEGIN SELECT RAISE(ABORT, 'immutable_attempt'); END;
