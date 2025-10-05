-- 1) Ajouter patient_id sur exercise_assignments si absent + index + FK
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name='exercise_assignments' AND column_name='patient_id'
  ) THEN
    ALTER TABLE exercise_assignments ADD COLUMN patient_id INTEGER NULL;
  END IF;
END$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM information_schema.table_constraints
    WHERE table_name='exercise_assignments'
      AND constraint_type='FOREIGN KEY'
      AND constraint_name='fk_exassign_patient'
  ) THEN
    ALTER TABLE exercise_assignments
      ADD CONSTRAINT fk_exassign_patient
      FOREIGN KEY (patient_id) REFERENCES users(id)
      ON DELETE SET NULL;
  END IF;
END$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_indexes
    WHERE tablename='exercise_assignments' AND indexname='idx_exassign_patient_id'
  ) THEN
    CREATE INDEX idx_exassign_patient_id ON exercise_assignments(patient_id);
  END IF;
END$$;
