# Generated manually
import uuid
from django.conf import settings
from django.db import migrations, models, transaction
import django.db.models.deletion

def _install_vector_extension(apps, schema_editor):
    """Install pgvector extension if available on PostgreSQL.
    Skipped if vector extension control file is not present in PostgreSQL installation.
    """
    if schema_editor.connection.vendor == "postgresql":
        try:
            with transaction.atomic():
                schema_editor.execute("CREATE EXTENSION IF NOT EXISTS vector")
        except Exception:
            pass


def _uninstall_vector_extension(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        try:
            with transaction.atomic():
                schema_editor.execute("DROP EXTENSION IF EXISTS vector")
        except Exception:
            pass


class Migration(migrations.Migration):
    initial = True
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.RunPython(
            _install_vector_extension,
            reverse_code=_uninstall_vector_extension,
        ),
        migrations.CreateModel(
            name='ChatSession',
            fields=[
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('hackathon_id', models.UUIDField(blank=True, null=True)),
                ('organization_id', models.UUIDField(blank=True, null=True)),
                ('user', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='ai_chat_sessions', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='ChatMessage',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('role', models.CharField(choices=[('user', 'User'), ('assistant', 'Assistant')], max_length=10)),
                ('content', models.TextField()),
                ('retrieved_chunk_ids', models.JSONField(default=list)),
                ('llm_model', models.CharField(blank=True, default='', max_length=100)),
                ('latency_ms', models.IntegerField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('session', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='messages', to='support_ai.chatsession')),
            ],
            options={
                'ordering': ['created_at'],
            },
        ),
        migrations.CreateModel(
            name='AIFeedback',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('rating', models.SmallIntegerField()),
                ('comment', models.TextField(blank=True, default='')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('message', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='feedback', to='support_ai.chatmessage')),
                ('user', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='ai_feedback_given', to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='DocumentChunk',
            fields=[
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('source_type', models.CharField(choices=[('article', 'Article'), ('faq', 'FAQ'), ('hackathon_rules', 'Hackathon Rules'), ('hackathon_description', 'Hackathon Description'), ('hackathon_rubric_criteria', 'Hackathon Rubric Criteria'), ('showcase_project', 'Showcase Project')], max_length=50)),
                ('source_id', models.UUIDField()),
                ('organization_id', models.UUIDField(blank=True, null=True)),
                ('hackathon_id', models.UUIDField(blank=True, null=True)),
                ('visibility', models.CharField(choices=[('public', 'Public'), ('organizer_only', 'Organizer Only'), ('platform_admin_only', 'Platform Admin Only')], default='public', max_length=20)),
                ('text', models.TextField()),
                ('embedding', models.JSONField(default=list)),
                ('chunk_index', models.IntegerField(default=0)),
                ('metadata', models.JSONField(default=dict)),
            ],
        ),
        migrations.AddIndex(
            model_name='chatsession',
            index=models.Index(fields=['user'], name='support_ai__user_id_01de49_idx'),
        ),
        migrations.AddConstraint(
            model_name='aifeedback',
            constraint=models.UniqueConstraint(fields=('message', 'user'), name='unique_ai_feedback_per_user'),
        ),
        migrations.AddIndex(
            model_name='documentchunk',
            index=models.Index(fields=['source_type', 'source_id'], name='support_ai__source__2cefa4_idx'),
        ),
        migrations.AddIndex(
            model_name='documentchunk',
            index=models.Index(fields=['visibility'], name='support_ai__visibil_e49a8d_idx'),
        ),
        migrations.AddIndex(
            model_name='documentchunk',
            index=models.Index(fields=['hackathon_id'], name='support_ai__hackath_a1fbbd_idx'),
        ),
        migrations.AddIndex(
            model_name='documentchunk',
            index=models.Index(fields=['organization_id'], name='support_ai__organiz_a70cc4_idx'),
        ),
        migrations.AddConstraint(
            model_name='documentchunk',
            constraint=models.UniqueConstraint(fields=('source_type', 'source_id', 'chunk_index'), name='unique_chunk_per_source'),
        ),
    ]
