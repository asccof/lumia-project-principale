"""appointments.patient_id nullable + ON DELETE SET NULL"""

from alembic import op
import sqlalchemy as sa

# Remplace ces IDs si tu utilises un format de révision différent
revision = '20250911_set_null_patient_id'
down_revision = None  # mets la dernière révision existante chez toi
branch_labels = None
depends_on = None

def upgrade():
    # 1) rendre nullable
    op.alter_column('appointments', 'patient_id',
                    existing_type=sa.Integer(),
                    nullable=True)

    # 2) recréer la FK en SET NULL
    # Le nom exact de contrainte peut varier; on drop puis on recrée proprement.
    try:
        op.drop_constraint('appointments_patient_id_fkey', 'appointments', type_='foreignkey')
    except Exception:
        # Si le nom diffère, laisse Alembic ignorer l'erreur et recrée la FK
        pass

    op.create_foreign_key(
        'appointments_patient_id_fkey',
        source_table='appointments',
        referent_table='users',
        local_cols=['patient_id'],
        remote_cols=['id'],
        ondelete='SET NULL',
    )

def downgrade():
    # Downgrade générique : repasser NOT NULL et FK sans ondelete
    try:
        op.drop_constraint('appointments_patient_id_fkey', 'appointments', type_='foreignkey')
    except Exception:
        pass

    op.create_foreign_key(
        'appointments_patient_id_fkey',
        source_table='appointments',
        referent_table='users',
        local_cols=['patient_id'],
        remote_cols=['id'],
        ondelete=None,
    )

    op.alter_column('appointments', 'patient_id',
                    existing_type=sa.Integer(),
                    nullable=False)
