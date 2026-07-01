from django.db import models
from django.core.validators import RegexValidator
from django.conf import settings
from django.utils.translation import gettext_lazy as _


def attendance_attachment_path(instance, filename):
    return f"attendance_attachments/{instance.employee.id}/{instance.date}/{filename}"


class Team(models.Model):
    """Nalivshiklar uchun 3 ta komanda (1-kom, 2-kom, 3-kom)."""

    CODE_CHOICES = [
        (1, "1-komanda"),
        (2, "2-komanda"),
        (3, "3-komanda"),
    ]

    code = models.PositiveSmallIntegerField("Komanda raqami", choices=CODE_CHOICES, unique=True)
    name = models.CharField("Nomi", max_length=64)
    description = models.TextField("Izoh", blank=True, null=True)

    class Meta:
        verbose_name = "Komanda"
        verbose_name_plural = "Komandalar"
        ordering = ["code"]

    def __str__(self):
        return self.name or f"{self.get_code_display()}"


class Employee(models.Model):
    LOCATION_CHOICES = [
        ('office', _('Ofis')),
        ('factory', _('Zavod')),
        ('remote', _('Masofaviy')),
        ('field', _('Dala')),
        ('other', _('Boshqa')),
    ]
    EMPLOYEE_TYPE_CHOICES = [
        ('full', _('To‘liq stavka')),
        ('half', _('15 kunlik/smena')),
        ('office', _('Ofis xodimi (davomatsiz)')),
        ('weekly', _('Haftada 1 kun (to‘liq stavka)')),
        ('guard', _('Qorovul (oyda 10 kun)')),
    ]
    ROLE_CHOICES = [
        ('production', _('Ishlab chiqarish xodimlari')),
        ('boshqarma', _('Boshqarma xodimlari')),
        ('nalivshik', _('Nalivshik')),
        ('other', _('Boshqa')),
    ]

    first_name = models.CharField(_("Ismi"), max_length=64)
    last_name = models.CharField(_("Familiyasi"), max_length=64)
    middle_name = models.CharField(_("Otchestvasi"), max_length=64, blank=True, default='')
    position = models.CharField(_("Lavozimi"), max_length=128)
    department = models.CharField(_("Bo'limi"), max_length=128, blank=True, null=True)
    location = models.CharField(_("Joylashuv"), max_length=20, choices=LOCATION_CHOICES, default='office')
    phone_number = models.CharField(
        "Telefon raqami", max_length=20, blank=True, null=True,
        validators=[RegexValidator(
            regex=r"^\+?998\d{9}$",
            message=_("Telefon raqamini to'g'ri (+998xxxxxxxxx) formatda kiriting.")
        )]
    )
    is_active = models.BooleanField(_("Aktiv"), default=True)
    hire_date = models.DateField(_("Ishga kirgan sana"), blank=True, null=True)
    production_bonus_eligible = models.BooleanField(
        "Ishlab chiqarish premiyasiga mos",
        default=False,
        help_text="Belgilangan xodimlarga oylik benzin ishlab chiqarish bo'yicha avtomatik premiya beriladi.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    employee_type = models.CharField(_("Xodim turi"), max_length=10, choices=EMPLOYEE_TYPE_CHOICES, default='full')
    role = models.CharField(_("Lavozim turi"), max_length=32, choices=ROLE_CHOICES, default='other')
    team = models.ForeignKey(
        Team,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="employees",
        verbose_name=_("Komanda"),
    )

    class Meta:
        verbose_name = "Xodim"
        verbose_name_plural = "Xodimlar"
        ordering = ['last_name', 'first_name']

    def __str__(self):
        return f"{self.get_full_name()} ({self.position})"

    def get_full_name(self):
        parts = [self.last_name, self.first_name]
        if self.middle_name:
            parts.append(self.middle_name)
        return " ".join(parts)


class NalivshikShiftOverride(models.Model):
    """
    Nalivshiklar uchun avtomatik smena siklini ma'lum sana uchun qo'lda
    o'zgartirish (override) modeli.
    """

    date = models.DateField("Sana", unique=True)
    day_team = models.ForeignKey(
        Team,
        on_delete=models.SET_NULL,
        related_name="day_overrides",
        null=True,
        blank=True,
        verbose_name="Kunduzgi komanda",
    )
    night_team = models.ForeignKey(
        Team,
        on_delete=models.SET_NULL,
        related_name="night_overrides",
        null=True,
        blank=True,
        verbose_name="Tungi komanda",
    )
    comment = models.CharField("Izoh", max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Nalivshik smena override"
        verbose_name_plural = "Nalivshik smena override'lari"
        ordering = ["-date"]

    def __str__(self):
        return f"{self.date} - kunduzgi: {self.day_team} / tungi: {self.night_team}"

class DayOff(models.Model):
    date = models.DateField(unique=True)
    reason = models.CharField(max_length=128)

    def __str__(self):
        return f"{self.date} - {self.reason}"

class Attendance(models.Model):
    STATUS_CHOICES = [
        ('present', _("Keldi")),
        ('absent', _("Kelmagan")),
        ('late', _("Kechikdi")),
        ('vacation', _("Ta'til")),
        ('sick', _("Kasal")),
        ('business', _("Ish safarida")),
        ('offday', _("Ish kuni emas")),
    ]
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='attendances', verbose_name="Xodim")
    date = models.DateField("Sana")
    status = models.CharField("Davomat holati", max_length=16, choices=STATUS_CHOICES)
    comment = models.TextField("Izoh/sabab", blank=True, null=True)
    # Fayl yuklash funksiyasi hozircha kerak emas
    # attachment = models.FileField("Ilova (hujjat/rasm)", upload_to=attendance_attachment_path, blank=True, null=True)
    created_at = models.DateTimeField("Qo'shilgan vaqt", auto_now_add=True)
    updated_at = models.DateTimeField("Yangilangan vaqt", auto_now=True)

    class Meta:
        unique_together = ('employee', 'date')
        verbose_name = "Davomat"
        verbose_name_plural = "Davomatlar"
        ordering = ['-date', 'employee']

    def __str__(self):
        return f"{self.date} - {self.employee} - {self.get_status_display()}"

class AttendanceImportLog(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    file_name = models.CharField(max_length=256)
    imported_at = models.DateTimeField(auto_now_add=True)
    record_count = models.PositiveIntegerField(default=0)
    success = models.BooleanField(default=True)
    log = models.TextField(blank=True, null=True)

class MonthlyEmployeeStat(models.Model):
    CURRENCY_CHOICES = [
        ('UZS', 'So‘m'),
        ('USD', 'Dollar'),
        ('EUR', 'Yevro'),
    ]
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='monthly_stats', verbose_name="Xodim")
    year = models.PositiveIntegerField("Yil")
    month = models.PositiveIntegerField("Oy")  # 1-12
    salary = models.DecimalField("Oylik", max_digits=12, decimal_places=2, default=0)
    salary_override = models.BooleanField(
        "Oylik qo'lda o'rnatilgan",
        default=False,
        help_text="True bo'lsa, oylik avvalgi oydan avtomatik o'zgarmaydi.",
    )
    bonus = models.DecimalField("Mukofot", max_digits=12, decimal_places=2, default=0)
    bonus_override = models.BooleanField(
        "Mukofot qo'lda o'rnatilgan",
        default=False,
        help_text="True bo'lsa, ishlab chiqarish premiyasi avtomatik yozilmaydi.",
    )
    penalty = models.DecimalField("Jarima", max_digits=12, decimal_places=2, default=0)
    days_in_month = models.PositiveIntegerField("Oy kunlari", default=0)
    worked_days = models.PositiveIntegerField("Ishlangan kunlar", default=0)
    accrued = models.DecimalField("Hisoblangan", max_digits=12, decimal_places=2, default=0)
    paid = models.DecimalField("To'langan", max_digits=12, decimal_places=2, default=0)
    paid_at = models.DateField("To'lov sanasi", null=True, blank=True)
    debt_start = models.DecimalField("Boshlang'ich qarzdorlik", max_digits=12, decimal_places=2, default=0)
    debt_end = models.DecimalField("Oxirgi qarzdorlik", max_digits=12, decimal_places=2, default=0)
    currency = models.CharField("Valyuta", max_length=3, choices=CURRENCY_CHOICES, default='UZS')
    manual_salary = models.BooleanField("Oylik faqat qo‘lda kiritiladi (ofis xodimi)", default=False)
    calculated_at = models.DateTimeField("Oxirgi hisoblash vaqti", null=True, blank=True)

    class Meta:
        unique_together = ('employee', 'year', 'month')
        verbose_name = "Oylik xodim statistikasi"
        verbose_name_plural = "Oylik xodim statistikasi"
        ordering = ['-year', '-month', 'employee']

    def __str__(self):
        return f"{self.year}-{self.month:02d} - {self.employee}"


class SalaryPayment(models.Model):
    """Oylik bo'yicha alohida to'lovlar (bir oyda bir necha marta)."""

    stat = models.ForeignKey(
        MonthlyEmployeeStat,
        on_delete=models.CASCADE,
        related_name='salary_payments',
        verbose_name="Oylik statistika",
    )
    amount = models.DecimalField("Summa", max_digits=12, decimal_places=2)
    paid_at = models.DateField("To'lov sanasi")
    note = models.CharField("Izoh", max_length=255, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Oylik to'lovi"
        verbose_name_plural = "Oylik to'lovlari"
        ordering = ['paid_at', 'pk']

    def __str__(self):
        return f"{self.paid_at} — {self.amount}"


class MonthlyProduction(models.Model):
    """Oylik benzin ishlab chiqarish hajmi (tonna) — premiya hisoblash uchun."""

    year = models.PositiveIntegerField("Yil")
    month = models.PositiveIntegerField("Oy")
    production_tons = models.DecimalField(
        "Ishlab chiqarish (tonna)",
        max_digits=10,
        decimal_places=2,
        default=0,
    )
    eligible_employees = models.ManyToManyField(
        Employee,
        blank=True,
        related_name='production_bonus_months',
        verbose_name="Premiya oluvchi xodimlar",
        help_text="Faqat shu oy uchun ishlab chiqarish premiyasi oladigan xodimlar.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('year', 'month')
        verbose_name = "Oylik ishlab chiqarish"
        verbose_name_plural = "Oylik ishlab chiqarish"
        ordering = ['-year', '-month']

    def __str__(self):
        return f"{self.year}-{self.month:02d}: {self.production_tons} t"
