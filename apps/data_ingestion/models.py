from django.db import models


class FIIDIIData(models.Model):
	"""
	Daily net flows for Foreign Institutional Investors (FII) and
	Domestic Institutional Investors (DII).
	"""

	date = models.DateField(unique=True)
	fii_net_value = models.DecimalField(max_digits=16, decimal_places=2)
	dii_net_value = models.DecimalField(max_digits=16, decimal_places=2)
	source = models.CharField(max_length=50, default='nse_bhavcopy')
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		ordering = ['-date']
		verbose_name = 'FII/DII Data'
		verbose_name_plural = 'FII/DII Data'
		indexes = [
			models.Index(fields=['date']),
			models.Index(fields=['source']),
		]

	def __str__(self):
		return (
			f"{self.date} | FII={self.fii_net_value} | "
			f"DII={self.dii_net_value}"
		)
