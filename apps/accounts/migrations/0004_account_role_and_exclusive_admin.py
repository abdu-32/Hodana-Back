from django.db import migrations, models


def set_exclusive_admin(apps, schema_editor):
    Account = apps.get_model("accounts", "Account")
    # Reset all accounts to non-admin participant
    Account.objects.all().update(is_platform_admin=False, role="participant")
    # Assign exclusive platform admin to Abdulhalim Aliye Ahmed
    Account.objects.filter(email__iexact="abdulhalimaliyi54@gmail.com").update(
        is_platform_admin=True,
        role="admin",
        verification_status="verified",
        is_suspended=False
    )


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0003_account_city_account_department_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="account",
            name="role",
            field=models.CharField(
                choices=[
                    ("participant", "Participant"),
                    ("organizer", "Organizer"),
                    ("judge", "Judge"),
                    ("admin", "Admin"),
                ],
                default="participant",
                max_length=20,
            ),
        ),
        migrations.RunPython(set_exclusive_admin, reverse_code=migrations.RunPython.noop),
    ]
