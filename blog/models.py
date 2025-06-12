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
        ('vacation', "Ta’til"),
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
    created_at = models.DateTimeField("Qo‘shilgan vaqt", auto_now_add=True)
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
