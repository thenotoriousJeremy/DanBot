import billboard
print('billboard imported, ChartData attr:', hasattr(billboard, 'ChartData'))
try:
    c = billboard.ChartData('hot-100', date='2019-12-27')
    print('chart len:', len(c))
    if len(c) > 0:
        print('top:', c[0].title, 'by', c[0].artist)
except Exception as e:
    import traceback
    traceback.print_exc()
