# Sets the shop's categories to the fixed list the owner chose, and keeps
# categories in A to Z order everywhere (menu, filter buttons, admin).

import re

from django.db import migrations


# The only categories the shop has, A to Z.
CATEGORY_NAMES = [
    "Briefcases",
    "Camera Bags",
    "Crossbody Bags",
    "Duffle Bags",
    "Gym Bags",
    "Handbags",
    "Kids Bags",
    "Laptop Bags",
    "Luggage Bags",
    "Lunchbox Bags",
    "Marathon Kit Bags",
    "Suit Carriers",
    "Suitcase Sets",
    "Suitcase Single",
    "Tote Bags",
]

# Old names that already mean one of the new categories (capitals, spaces and
# punctuation do not matter). An old category like this is renamed, or merged
# into the new category when that one already exists.
SAME_AS = {
    "Briefcases": ["briefcase"],
    "Camera Bags": ["camera", "camerabag"],
    "Crossbody Bags": ["crossbody", "crossbodybag", "crossbodies"],
    "Duffle Bags": ["duffle", "dufflebag", "duffel", "duffelbag", "duffelbags"],
    "Gym Bags": ["gym", "gymbag"],
    "Handbags": ["handbag"],
    "Kids Bags": ["kid", "kids", "kidbag", "kidbags", "kidsbag"],
    "Laptop Bags": ["laptop", "laptops", "laptopbag"],
    "Luggage Bags": ["luggage", "luggagebag"],
    "Lunchbox Bags": ["lunchbox", "lunchboxbag", "lunchbag", "lunchbags"],
    "Marathon Kit Bags": ["marathonkitbag", "maratonkitbag", "maratonkitbags"],
    "Suit Carriers": ["suitcarrier"],
    "Suitcase Sets": ["suitcaseset", "suitecaseset", "suitecasesets"],
    "Suitcase Single": [
        "suitcasesingles", "suitecasesingle", "singlesuitcase", "singlesuitcases",
    ],
    "Tote Bags": ["tote", "totes", "totebag"],
}


def simplify(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())


MEANS = {simplify(name): name for name in CATEGORY_NAMES}

for new_name, old_names in SAME_AS.items():
    for old_name in old_names:
        MEANS[old_name] = new_name


def set_categories(apps, schema_editor):

    db = schema_editor.connection.alias
    Category = apps.get_model("store", "Category")
    Bag = apps.get_model("store", "Bag")

    categories = Category.objects.using(db)

    def merge(old, keep):
        Bag.objects.using(db).filter(category=old).update(category=keep)
        old.delete()

    # 1. Old categories that mean one of the new ones: rename or merge.
    for old in list(categories.order_by("id")):

        new_name = MEANS.get(simplify(old.name))

        if new_name is None or old.name == new_name:
            continue

        keep = (
            categories.filter(name=new_name)
            .exclude(pk=old.pk)
            .order_by("id")
            .first()
        )

        if keep is None:
            old.name = new_name
            old.save(update_fields=["name"])
        else:
            merge(old, keep)

    # 2. Every new category exists, exactly once.
    for name in CATEGORY_NAMES:

        same = list(categories.filter(name=name).order_by("id"))

        if not same:
            categories.create(name=name)

        for extra in same[1:]:
            merge(extra, same[0])

    # 3. Any other category: an empty one is removed. One that still holds
    #    bags stays, because only the owner knows where those bags belong.
    still_used = []

    for old in list(categories.exclude(name__in=CATEGORY_NAMES)):

        count = Bag.objects.using(db).filter(category=old).count()

        if count == 0:
            old.delete()
        else:
            still_used.append(
                f"{old.name} ({count} bag{'' if count == 1 else 's'})"
            )

    if still_used:
        print(
            "\n  NOTE: these old categories still hold bags, so they were kept: "
            + ", ".join(still_used)
            + ".\n  In the admin, move those bags to one of the new categories"
            " (Bags > open the bag > Category),\n  then delete the old category."
        )


class Migration(migrations.Migration):

    dependencies = [
        ('store', '0011_alter_bag_homepage_order_alter_bag_show_on_homepage'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='category',
            options={'ordering': ['name'], 'verbose_name_plural': 'categories'},
        ),
        migrations.RunPython(set_categories, migrations.RunPython.noop),
    ]