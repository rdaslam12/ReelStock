from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0008_alter_blogpost_options_blogpost_home_order_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="generatedvideo",
            name="duration",
            field=models.CharField(blank=True, default="4", max_length=20),
        ),
    ]
