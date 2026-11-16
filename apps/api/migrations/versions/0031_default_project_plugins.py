"""Enable the reviewed IFC and calculation Plugins for newly created Projects."""

from alembic import op

revision = "0031_default_project_plugins"
down_revision = "0030_project_documents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Initialize selections in the Project creation transaction. Existing Projects
    # are untouched, and subsequent user enable/disable choices remain authoritative.
    op.execute(
        """
        CREATE FUNCTION initialize_project_plugin_defaults() RETURNS trigger AS $$
        BEGIN
            INSERT INTO project_plugin_selections (project_id, plugin_id)
            VALUES (NEW.id, 'ifc-viewer'), (NEW.id, 'calculation-source-object');
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER initialize_project_plugin_defaults
        AFTER INSERT ON projects
        FOR EACH ROW EXECUTE FUNCTION initialize_project_plugin_defaults()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER initialize_project_plugin_defaults ON projects")
    op.execute("DROP FUNCTION initialize_project_plugin_defaults()")
