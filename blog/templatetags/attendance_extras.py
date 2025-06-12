from django import template
register = template.Library()

@register.filter
def get_item(dictionary, key):
    return dictionary.get(str(key))

@register.filter
def dict_get(dict_obj, key):
    if dict_obj and key in dict_obj:
        return dict_obj[key]
    return ""


@register.filter(name='add_class')
def add_class(field, css):
    return field.as_widget(attrs={"class": css})
