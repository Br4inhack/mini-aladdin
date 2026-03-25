from django.contrib import admin
from .models import FIIDIIData


@admin.register(FIIDIIData)
class FIIDIIDataAdmin(admin.ModelAdmin):
	list_display = ('date', 'fii_net_value', 'dii_net_value', 'source')
	list_filter = ('source',)
	search_fields = ('source',)
	ordering = ('-date',)
