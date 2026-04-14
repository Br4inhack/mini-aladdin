import os

# 1. Update serializers.py
serializers_path = r'd:\Projects\mini-aladdin\apps\portfolio\serializers.py'
with open(serializers_path, 'r', encoding='utf-8') as f:
    ser_content = f.read()

new_serializer = '''
class MacroIndicatorSerializer(serializers.ModelSerializer):
    formatted_value = serializers.SerializerMethodField()
    trend = serializers.SerializerMethodField()

    class Meta:
        model = MacroIndicator
        fields = ['indicator_name', 'value', 'date', 'source', 'formatted_value', 'trend']

    def get_formatted_value(self, obj):
        name = (obj.indicator_name or '').lower()
        val = obj.value
        if val is None:
            return '—'
        if 'rate' in name:
            return f"{float(val):.2f}%"
        if 'gdp' in name:
            # Assuming value is in trillions for formatting, or needs T
            return f"{float(val):.2f}T"
        return f"{float(val):.2f}"

    def get_trend(self, obj):
        # Find the previous record for this indicator
        prev = MacroIndicator.objects.filter(
            indicator_name=obj.indicator_name,
            date__lt=obj.date
        ).order_by('-date').first()
        if not prev or prev.value is None or obj.value is None:
            return 'FLAT'
        if obj.value > prev.value:
            return 'UP'
        elif obj.value < prev.value:
            return 'DOWN'
        return 'FLAT'
'''

if 'class MacroIndicatorSerializer' not in ser_content:
    if 'from apps.portfolio.models import' in ser_content:
        # We need to make sure MacroIndicator is imported. It should be, or we can just add it.
        # It's better to just ensure it's imported in serializers.py.
        pass
    ser_content += new_serializer
    
    # Let's ensure MacroIndicator is imported
    ser_content = ser_content.replace(
        'from apps.portfolio.models import (',
        'from apps.portfolio.models import (\n    MacroIndicator,'
    )
    with open(serializers_path, 'w', encoding='utf-8') as f:
        f.write(ser_content)
    print("MacroIndicatorSerializer inserted.")

# 2. Update api_views.py
api_views_path = r'd:\Projects\mini-aladdin\apps\portfolio\api_views.py'
with open(api_views_path, 'r', encoding='utf-8') as f:
    api_content = f.read()

new_view = '''
from django.db.models import Max

class MacroIndicatorView(APIView):
    """VIEW 21: Returns latest value for each unique MacroIndicator."""
    permission_classes = []

    def get(self, request, portfolio_id):
        try:
            get_object_or_404(Portfolio, id=portfolio_id)
            
            # Annnotate latest date for each indicator
            latest_indicators = MacroIndicator.objects.values('indicator_name').annotate(latest_date=Max('date'))
            
            records = []
            for item in latest_indicators:
                record = MacroIndicator.objects.filter(
                    indicator_name=item['indicator_name'],
                    date=item['latest_date']
                ).first()
                if record:
                    records.append(record)
                    
            serializer = MacroIndicatorSerializer(records, many=True)
            return Response(serializer.data)
        except Exception as e:
            return Response({'error': str(e)}, status=500)
'''

if 'class MacroIndicatorView' not in api_content:
    # Ensure imported models in api_views include MacroIndicator
    if 'MacroIndicator' not in api_content:
        api_content = api_content.replace(
            'from apps.portfolio.models import (',
            'from apps.portfolio.models import (\n    MacroIndicator,'
        )
    # Ensure imported serializers include MacroIndicatorSerializer
    if 'MacroIndicatorSerializer' not in api_content:
        api_content = api_content.replace(
            'from apps.portfolio.serializers import (',
            'from apps.portfolio.serializers import (\n    MacroIndicatorSerializer,'
        )
    
    insert_before = 'class HealthCheckAPIView(APIView):'
    api_content = api_content.replace(insert_before, new_view + '\n' + insert_before, 1)

    with open(api_views_path, 'w', encoding='utf-8') as f:
        f.write(api_content)
    print("MacroIndicatorView inserted.")

# 3. Update urls.py
urls_path = r'd:\Projects\mini-aladdin\apps\portfolio\urls.py'
with open(urls_path, 'r', encoding='utf-8') as f:
    urls_content = f.read()

if 'macro-indicators' not in urls_content:
    new_url = "    path('portfolio/<int:portfolio_id>/macro-indicators/', api_views.MacroIndicatorView.as_view(), name='api-macro-indicators'),\n"
    urls_content = urls_content.replace(
        "path('health/', api_views.HealthCheckAPIView.as_view(), name='api-health'),",
        new_url + "    path('health/', api_views.HealthCheckAPIView.as_view(), name='api-health'),"
    )
    with open(urls_path, 'w', encoding='utf-8') as f:
        f.write(urls_content)
    print("MacroIndicator url added.")
