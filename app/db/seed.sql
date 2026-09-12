INSERT INTO parents VALUES (1, 'Alex Tan'), (2, 'Jamie Lim');
INSERT INTO students VALUES
    (1, 1, 'Avery Tan'), (2, 1, 'Kai Tan'),
    (3, 2, 'Riley Lim'), (4, 2, 'Sam Lim'), (5, 2, 'Robin Lim'), (6, 2, 'Jules Lim');
INSERT INTO trial_classes VALUES
    (1, 'Science explorers', '2026-10-03T02:00:00.000000Z'),
    (2, 'Math puzzles', '2026-10-04T02:00:00.000000Z'),
    (3, 'Space science', '2026-10-05T02:00:00.000000Z');
INSERT INTO bookings (id, student_id, trial_class_id, idempotency_key, created_at, updated_at) VALUES
    (1, 2, 2, '1:seed-1', '2026-09-09T00:00:00.000000Z', '2026-09-09T00:00:00.000000Z'),
    (2, 4, 2, '2:seed-2', '2026-09-09T00:00:00.000000Z', '2026-09-09T00:00:00.000000Z'),
    (3, 5, 2, '2:seed-3', '2026-09-09T00:00:00.000000Z', '2026-09-09T00:00:00.000000Z'),
    (4, 1, 1, '1:seed-failure', '2026-09-09T00:00:00.000000Z', '2026-09-09T00:00:00.000000Z');
INSERT INTO payment_attempts (id, booking_id, requested_outcome, idempotency_key, created_at) VALUES
    (1, 1, 'success', '1:seed-1', '2026-09-09T00:01:00.000000Z'),
    (2, 2, 'success', '2:seed-2', '2026-09-09T00:01:00.000000Z'),
    (3, 3, 'success', '2:seed-3', '2026-09-09T00:01:00.000000Z');
UPDATE payment_attempts SET outcome = 'succeeded';
UPDATE bookings SET status = 'confirmed', updated_at = '2026-09-09T00:01:00.000000Z'
WHERE id IN (1, 2, 3);
