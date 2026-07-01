"""Tarjima qilinadigan umumiy matnlar."""
from django.utils.translation import gettext_lazy as _

MONTH_NAME_CHOICES = [
    (1, _('Yanvar')),
    (2, _('Fevral')),
    (3, _('Mart')),
    (4, _('Aprel')),
    (5, _('May')),
    (6, _('Iyun')),
    (7, _('Iyul')),
    (8, _('Avgust')),
    (9, _('Sentabr')),
    (10, _('Oktabr')),
    (11, _('Noyabr')),
    (12, _('Dekabr')),
]

WEEKDAY_NAMES = [
    (0, _('Dushanba')),
    (1, _('Seshanba')),
    (2, _('Chorshanba')),
    (3, _('Payshanba')),
    (4, _('Juma')),
    (5, _('Shanba')),
    (6, _('Yakshanba')),
]
