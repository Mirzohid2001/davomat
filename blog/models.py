from django.db import models
from django.core.validators import RegexValidator
from django.conf import settings

def attendance_attachment_path(instance, filename):
    return f"attendance_attachments/{instance.employee.id}/{instance.date}/{filename}"

class Employee(models.Model):
    LOCATION_CHOICES = [
        ('office', 'Ofis'),
        ('factory', 'Zavod'),
        ('remote', 'Masofaviy'),
        ('field', 'Dala'),
        ('other', 'Boshqa'),
    ]
    
    first_name = models.CharField("Ismi", max_length=64)
    last_name = models.CharField("Familiyasi", max_length=64)
    position = models.CharField("Lavozimi", max_length=128)
    department = models.CharField("Bo'limi", max_length=128, blank=True, null=True)
    location = models.CharField("Joylashuv", max_length=20, choices=LOCATION_CHOICES, default='office')
    phone_number = models.CharField(
        "Telefon raqami", max_length=20, blank=True, null=True,
        validators=[RegexValidator(
            regex=r"^\+?998\d{9}$",
            message="Telefon raqamini to'g'ri (+998xxxxxxxxx) formatda kiriting."
        )]
    )
    is_active = models.BooleanField("Aktiv", default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Xodim"
        verbose_name_plural = "Xodimlar"
        ordering = ['last_name', 'first_name']

    def __str__(self):
        return f"{self.last_name} {self.first_name} ({self.position})"

class DayOff(models.Model):
    date = models.DateField(unique=True)
    reason = models.CharField(max_length=128)

    def __str__(self):
        return f"{self.date} - {self.reason}"

class Attendance(models.Model):
    STATUS_CHOICES = [
        ('present', "Keldi"),
        ('absent', "Kelmagan"),
        ('late', "Kechikdi"),
        ('vacation', "Ta'til"),
        ('sick', "Kasal"),
        ('business', "Ish safarida"),
        ('offday', "Ish kuni emas"),
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
    bonus = models.DecimalField("Mukofot", max_digits=12, decimal_places=2, default=0)
    penalty = models.DecimalField("Jarima", max_digits=12, decimal_places=2, default=0)
    days_in_month = models.PositiveIntegerField("Oy kunlari", default=0)
    worked_days = models.PositiveIntegerField("Ishlangan kunlar", default=0)
    accrued = models.DecimalField("Hisoblangan", max_digits=12, decimal_places=2, default=0)
    paid = models.DecimalField("To'langan", max_digits=12, decimal_places=2, default=0)
    debt_start = models.DecimalField("Boshlang'ich qarzdorlik", max_digits=12, decimal_places=2, default=0)
    debt_end = models.DecimalField("Oxirgi qarzdorlik", max_digits=12, decimal_places=2, default=0)
    currency = models.CharField("Valyuta", max_length=3, choices=CURRENCY_CHOICES, default='UZS')

    class Meta:
        unique_together = ('employee', 'year', 'month')
        verbose_name = "Oylik xodim statistikasi"
        verbose_name_plural = "Oylik xodim statistikasi"
        ordering = ['-year', '-month', 'employee']

    def __str__(self):
        return f"{self.year}-{self.month:02d} - {self.employee}"
