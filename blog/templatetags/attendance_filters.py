from django import template

register = template.Library()

@register.filter
def status_color(status):
    """Return Bootstrap color class based on attendance status"""
    status_colors = {
        'present': 'success',
        'late': 'warning',
        'absent': 'danger',
        'vacation': 'info',
        'labor_leave': 'primary',
        'business': 'primary',
        'offday': 'secondary',
    }
    return status_colors.get(status.lower(), 'dark')

@register.filter
def status_icon(status):
    """Return Bootstrap icon based on attendance status"""
    status_icons = {
        'present': 'check-circle-fill',
        'late': 'exclamation-triangle-fill',
        'absent': 'x-circle-fill',
        'vacation': 'umbrella-fill',
        'labor_leave': 'calendar2-heart-fill',
        'business': 'briefcase-fill',
        'offday': 'calendar-x-fill',
    }
    return status_icons.get(status.lower(), 'question-circle-fill')

@register.filter
def status_color_rgb(status):
    """Return RGB color values for chart styling"""
    status_colors_rgb = {
        'present': '40, 167, 69',
        'late': '255, 193, 7',
        'absent': '220, 53, 69',
        'vacation': '23, 162, 184',
        'labor_leave': '79, 70, 229',
        'business': '111, 66, 193',
        'offday': '108, 117, 125',
    }
    return status_colors_rgb.get(status.lower(), '108, 117, 125')
