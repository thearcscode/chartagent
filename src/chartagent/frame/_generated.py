# @generated from flint-chart@0.5.1 — DO NOT EDIT.
# Regenerate: node tools/extract.mjs <bundle> src/chartagent/frame/vocab.json \
#             && python tools/generate.py src/chartagent/frame/vocab.json <out>
from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

FLINT_VERSION = '0.5.1'
BUNDLE_SHA256 = 'd82901aa5bf701f892e11b6e68b28cfc7ec6cd7ac8cac35bdf2e9a0248a23e06'
CHART_TYPES = ['Area Chart', 'Bar Chart', 'Bar Table', 'Boxplot', 'Bubble Chart', 'Bullet Chart', 'Bump Chart', 'Calendar Heatmap', 'Candlestick Chart', 'Choropleth', 'Combo Chart', 'Connected Scatter Plot', 'Density Contour', 'Density Plot', 'Donut Chart', 'Doughnut Chart', 'ECDF Plot', 'Funnel Chart', 'Gantt Chart', 'Gauge Chart', 'Grouped Bar Chart', 'Heatmap', 'Histogram', 'KPI Card', 'Line Chart', 'Lollipop Chart', 'Map', 'Network Graph', 'Parallel Coordinates', 'Pie Chart', 'Pyramid Chart', 'Radar Chart', 'Range Area Chart', 'Ranged Dot Plot', 'Regression', 'Rose Chart', 'Sankey Diagram', 'Scatter Plot', 'Slope Chart', 'Sparkline', 'Stacked Bar Chart', 'Streamgraph', 'Strip Plot', 'Sunburst Chart', 'Tree', 'Treemap', 'Violin Plot', 'Waterfall Chart']
CHANNELS = ['x', 'y', 'x2', 'y2', 'id', 'color', 'opacity', 'size', 'shape', 'strokeDash', 'column', 'row', 'latitude', 'longitude', 'radius', 'detail', 'group', 'open', 'high', 'low', 'close', 'angle', 'order', 'metric', 'value', 'goal']
SEMANTIC_TYPES = ['DateTime', 'Date', 'Time', 'Timestamp', 'Year', 'Quarter', 'Month', 'Week', 'Day', 'Hour', 'YearMonth', 'YearQuarter', 'YearWeek', 'Decade', 'Duration', 'Quantity', 'Count', 'Amount', 'Price', 'Percentage', 'Temperature', 'Profit', 'PercentageChange', 'Sentiment', 'Correlation', 'Rank', 'ID', 'Score', 'Latitude', 'Longitude', 'Country', 'State', 'City', 'Region', 'Address', 'ZipCode', 'Category', 'Name', 'Status', 'Boolean', 'Direction', 'Range', 'Number', 'Unknown']
THEME_PRESETS = ['nyt', 'economist', 'swiss', 'nature', 'mckinsey', 'datawrapper', 'powerbi', 'powerbi-light', 'pop', 'cartoon']

ChartType = Literal['Area Chart', 'Bar Chart', 'Bar Table', 'Boxplot', 'Bubble Chart', 'Bullet Chart', 'Bump Chart', 'Calendar Heatmap', 'Candlestick Chart', 'Choropleth', 'Combo Chart', 'Connected Scatter Plot', 'Density Contour', 'Density Plot', 'Donut Chart', 'Doughnut Chart', 'ECDF Plot', 'Funnel Chart', 'Gantt Chart', 'Gauge Chart', 'Grouped Bar Chart', 'Heatmap', 'Histogram', 'KPI Card', 'Line Chart', 'Lollipop Chart', 'Map', 'Network Graph', 'Parallel Coordinates', 'Pie Chart', 'Pyramid Chart', 'Radar Chart', 'Range Area Chart', 'Ranged Dot Plot', 'Regression', 'Rose Chart', 'Sankey Diagram', 'Scatter Plot', 'Slope Chart', 'Sparkline', 'Stacked Bar Chart', 'Streamgraph', 'Strip Plot', 'Sunburst Chart', 'Tree', 'Treemap', 'Violin Plot', 'Waterfall Chart']
SemanticTypeName = Literal['DateTime', 'Date', 'Time', 'Timestamp', 'Year', 'Quarter', 'Month', 'Week', 'Day', 'Hour', 'YearMonth', 'YearQuarter', 'YearWeek', 'Decade', 'Duration', 'Quantity', 'Count', 'Amount', 'Price', 'Percentage', 'Temperature', 'Profit', 'PercentageChange', 'Sentiment', 'Correlation', 'Rank', 'ID', 'Score', 'Latitude', 'Longitude', 'Country', 'State', 'City', 'Region', 'Address', 'ZipCode', 'Category', 'Name', 'Status', 'Boolean', 'Direction', 'Range', 'Number', 'Unknown']
ThemePresetName = Literal['nyt', 'economist', 'swiss', 'nature', 'mckinsey', 'datawrapper', 'powerbi', 'powerbi-light', 'pop', 'cartoon']


class GeneratedProperties(BaseModel):
    """Per-(backend, chart type) chartProperties model. extra='forbid', keys mode."""

    model_config = ConfigDict(extra="forbid")
    flint_version: ClassVar[str] = FLINT_VERSION
    bundle_sha256: ClassVar[str] = BUNDLE_SHA256


class ChartjsArea_ChartProperties(GeneratedProperties):
    """chartjs / Area Chart. channels: x, y, color, opacity, column, row"""
    interpolate: Literal['linear', 'monotone', 'step', 'step-before', 'step-after', 'basis', 'cardinal', 'catmull-rom'] | None = Field(default=None)
    opacity: float | None = Field(default=0.4, json_schema_extra={'min': 0.1, 'max': 1, 'step': 0.05})  # data-dependent: check() runs client-side
    stackMode: Literal['layered'] | None = Field(default=None)

class ChartjsBar_ChartProperties(GeneratedProperties):
    """chartjs / Bar Chart. channels: x, y, color, opacity, column, row"""
    cornerRadius: float | None = Field(default=0, json_schema_extra={'min': 0, 'max': 15, 'step': 1})
    sort: Literal['value-desc', 'value-asc'] | None = Field(default=None)  # data-dependent: check() runs client-side

class ChartjsBubble_ChartProperties(GeneratedProperties):
    """chartjs / Bubble Chart. channels: x, y, size, color, opacity, column, row"""
    opacity: float | None = Field(default=0.6, json_schema_extra={'min': 0.1, 'max': 1, 'step': 0.05})

class ChartjsBump_ChartProperties(GeneratedProperties):
    """chartjs / Bump Chart. channels: x, y, color, detail, column, row"""
    pass

class ChartjsCombo_ChartProperties(GeneratedProperties):
    """chartjs / Combo Chart. channels: x, y, column, row"""
    cornerRadius: float | None = Field(default=0, json_schema_extra={'min': 0, 'max': 15, 'step': 1})

class ChartjsConnected_Scatter_PlotProperties(GeneratedProperties):
    """chartjs / Connected Scatter Plot. channels: x, y, order, color, detail, column, row"""
    pass

class ChartjsDoughnut_ChartProperties(GeneratedProperties):
    """chartjs / Doughnut Chart. channels: size, color, column, row"""
    innerRadius: float | None = Field(default=55, json_schema_extra={'min': 20, 'max': 80, 'step': 5})
    sortSlices: Literal['none', 'descending', 'ascending'] | None = Field(default='none')

class ChartjsECDF_PlotProperties(GeneratedProperties):
    """chartjs / ECDF Plot. channels: x, color, detail, column, row"""
    showPoints: bool | None = Field(default=False)

class ChartjsGantt_ChartProperties(GeneratedProperties):
    """chartjs / Gantt Chart. channels: y, x, x2, color, column, row"""
    taskHeight: float | None = Field(default=70, json_schema_extra={'min': 40, 'max': 90, 'step': 5})
    cornerRadius: float | None = Field(default=2, json_schema_extra={'min': 0, 'max': 8, 'step': 1})
    intervalLabels: bool | None = Field(default=False)

class ChartjsGrouped_Bar_ChartProperties(GeneratedProperties):
    """chartjs / Grouped Bar Chart. channels: x, y, group, color, column, row"""
    dodge: Literal['auto', 'local', 'global'] | None = Field(default='auto')  # data-dependent: check() runs client-side
    sort: Literal['value-desc', 'value-asc'] | None = Field(default=None)  # data-dependent: check() runs client-side

class ChartjsHistogramProperties(GeneratedProperties):
    """chartjs / Histogram. channels: x, color, column, row"""
    binCount: float | None = Field(default=0, json_schema_extra={'min': 5, 'max': 50, 'step': 1})

class ChartjsLine_ChartProperties(GeneratedProperties):
    """chartjs / Line Chart. channels: x, y, color, opacity, column, row"""
    interpolate: Literal['linear', 'monotone', 'step', 'step-before', 'step-after', 'basis', 'cardinal', 'catmull-rom'] | None = Field(default=None)

class ChartjsLollipop_ChartProperties(GeneratedProperties):
    """chartjs / Lollipop Chart. channels: x, y, color, column, row"""
    dotSize: float | None = Field(default=80, json_schema_extra={'min': 20, 'max': 300, 'step': 10})

class ChartjsPie_ChartProperties(GeneratedProperties):
    """chartjs / Pie Chart. channels: size, color, column, row"""
    innerRadius: float | None = Field(default=0, json_schema_extra={'min': 0, 'max': 60, 'step': 5})
    sortSlices: Literal['none', 'descending', 'ascending'] | None = Field(default='none')

class ChartjsRadar_ChartProperties(GeneratedProperties):
    """chartjs / Radar Chart. channels: x, y, color, column, row"""
    filled: list[object] | None = Field(default=None)
    fillOpacity: float | None = Field(default=0.3, json_schema_extra={'min': 0.05, 'max': 0.8, 'step': 0.05})

class ChartjsRange_Area_ChartProperties(GeneratedProperties):
    """chartjs / Range Area Chart. channels: x, y, y2, color, column, row"""
    pass

class ChartjsRose_ChartProperties(GeneratedProperties):
    """chartjs / Rose Chart. channels: x, y, color, column, row"""
    alignment: Literal['left', 'center'] | None = Field(default=None)
    sortSlices: Literal['none', 'descending', 'ascending'] | None = Field(default='none')

class ChartjsScatter_PlotProperties(GeneratedProperties):
    """chartjs / Scatter Plot. channels: x, y, color, size, opacity, column, row"""
    opacity: float | None = Field(default=1, json_schema_extra={'min': 0.1, 'max': 1, 'step': 0.05})

class ChartjsSlope_ChartProperties(GeneratedProperties):
    """chartjs / Slope Chart. channels: x, y, color, detail, column, row"""
    pass

class ChartjsStacked_Bar_ChartProperties(GeneratedProperties):
    """chartjs / Stacked Bar Chart. channels: x, y, color, column, row"""
    sort: Literal['value-desc', 'value-asc'] | None = Field(default=None)  # data-dependent: check() runs client-side

class ChartjsStrip_PlotProperties(GeneratedProperties):
    """chartjs / Strip Plot. channels: x, y, color, size, column, row"""
    stepWidth: float | None = Field(default=20, json_schema_extra={'min': 10, 'max': 100, 'step': 5})
    pointSize: float | None = Field(default=0, json_schema_extra={'min': 0, 'max': 150, 'step': 5})
    opacity: float | None = Field(default=0, json_schema_extra={'min': 0, 'max': 1, 'step': 0.05})

class ChartjsWaterfall_ChartProperties(GeneratedProperties):
    """chartjs / Waterfall Chart. channels: x, y, color, column, row"""
    pass

class EchartsArea_ChartProperties(GeneratedProperties):
    """echarts / Area Chart. channels: x, y, color, opacity, column, row"""
    interpolate: Literal['linear', 'monotone', 'step', 'step-before', 'step-after', 'basis', 'cardinal', 'catmull-rom'] | None = Field(default=None)
    opacity: float | None = Field(default=0.7, json_schema_extra={'min': 0.1, 'max': 1, 'step': 0.05})  # data-dependent: check() runs client-side
    stackMode: Literal['normalize', 'center', 'layered'] | None = Field(default=None)

class EchartsBar_ChartProperties(GeneratedProperties):
    """echarts / Bar Chart. channels: x, y, color, opacity, column, row"""
    cornerRadius: float | None = Field(default=0, json_schema_extra={'min': 0, 'max': 15, 'step': 1})
    sort: Literal['value-desc', 'value-asc'] | None = Field(default=None)  # data-dependent: check() runs client-side

class EchartsBoxplotProperties(GeneratedProperties):
    """echarts / Boxplot. channels: x, y, color, opacity, column, row"""
    whiskerMethod: Literal['iqr', 'minmax'] | None = Field(default='iqr')
    showPoints: bool | None = Field(default=False)  # data-dependent: check() runs client-side
    showOutliers: bool | None = Field(default=True)  # data-dependent: check() runs client-side
    dodge: Literal['auto', 'local', 'global'] | None = Field(default='auto')  # data-dependent: check() runs client-side

class EchartsBullet_ChartProperties(GeneratedProperties):
    """echarts / Bullet Chart. channels: y, x, goal, color, column, row"""
    pass

class EchartsBump_ChartProperties(GeneratedProperties):
    """echarts / Bump Chart. channels: x, y, color, detail, column, row"""
    pass

class EchartsCalendar_HeatmapProperties(GeneratedProperties):
    """echarts / Calendar Heatmap. channels: x, color"""
    colorScheme: Literal['viridis', 'github', 'blues', 'greens', 'reds', 'oranges', 'purples'] | None = Field(default=None)  # data-dependent: check() runs client-side

class EchartsCandlestick_ChartProperties(GeneratedProperties):
    """echarts / Candlestick Chart. channels: x, open, high, low, close, column, row"""
    showMA: bool | None = Field(default=False)
    maWindow: float | None = Field(default=5, json_schema_extra={'min': 3, 'max': 30, 'step': 1})

class EchartsConnected_Scatter_PlotProperties(GeneratedProperties):
    """echarts / Connected Scatter Plot. channels: x, y, order, color, detail, column, row"""
    pass

class EchartsDensity_PlotProperties(GeneratedProperties):
    """echarts / Density Plot. channels: x, color, column, row"""
    bandwidth: float | None = Field(default=0, json_schema_extra={'min': 0.05, 'max': 2, 'step': 0.05})

class EchartsECDF_PlotProperties(GeneratedProperties):
    """echarts / ECDF Plot. channels: x, color, detail, column, row"""
    showPoints: bool | None = Field(default=False)

class EchartsFunnel_ChartProperties(GeneratedProperties):
    """echarts / Funnel Chart. channels: y, size"""
    sort: Literal['descending', 'ascending', 'none'] | None = Field(default=None)
    orient: Literal['vertical', 'horizontal'] | None = Field(default=None)
    gap: float | None = Field(default=2, json_schema_extra={'min': 0, 'max': 20, 'step': 1})

class EchartsGantt_ChartProperties(GeneratedProperties):
    """echarts / Gantt Chart. channels: y, x, x2, color, detail, column, row"""
    taskHeight: float | None = Field(default=70, json_schema_extra={'min': 40, 'max': 90, 'step': 5})
    cornerRadius: float | None = Field(default=2, json_schema_extra={'min': 0, 'max': 8, 'step': 1})
    intervalLabels: bool | None = Field(default=False)

class EchartsGauge_ChartProperties(GeneratedProperties):
    """echarts / Gauge Chart. channels: size, column"""
    min: float | None = Field(default=0, json_schema_extra={'min': 0, 'max': 1000, 'step': 10})
    max: float | None = Field(default=100, json_schema_extra={'min': 0, 'max': 10000, 'step': 100})
    showProgress: list[object] | None = Field(default=None)

class EchartsGrouped_Bar_ChartProperties(GeneratedProperties):
    """echarts / Grouped Bar Chart. channels: x, y, group, color, column, row"""
    dodge: Literal['auto', 'local', 'global'] | None = Field(default='auto')  # data-dependent: check() runs client-side
    sort: Literal['value-desc', 'value-asc'] | None = Field(default=None)  # data-dependent: check() runs client-side

class EchartsHeatmapProperties(GeneratedProperties):
    """echarts / Heatmap. channels: x, y, color, column, row"""
    colorScheme: Literal['viridis', 'inferno', 'magma', 'plasma', 'turbo', 'blues', 'reds', 'greens', 'oranges', 'purples', 'greys', 'blueorange', 'redblue'] | None = Field(default=None)  # data-dependent: check() runs client-side

class EchartsHistogramProperties(GeneratedProperties):
    """echarts / Histogram. channels: x, color, column, row"""
    binCount: float | None = Field(default=0, json_schema_extra={'min': 5, 'max': 50, 'step': 1})

class EchartsLine_ChartProperties(GeneratedProperties):
    """echarts / Line Chart. channels: x, y, color, opacity, column, row"""
    interpolate: Literal['linear', 'monotone', 'step', 'step-before', 'step-after', 'basis', 'cardinal', 'catmull-rom'] | None = Field(default=None)
    showPoints: bool | None = Field(default=False)

class EchartsLollipop_ChartProperties(GeneratedProperties):
    """echarts / Lollipop Chart. channels: x, y, color, column, row"""
    dotSize: float | None = Field(default=80, json_schema_extra={'min': 20, 'max': 300, 'step': 10})
    sort: Literal['value-desc', 'value-asc'] | None = Field(default=None)  # data-dependent: check() runs client-side

class EchartsNetwork_GraphProperties(GeneratedProperties):
    """echarts / Network Graph. channels: x, y, size"""
    layout: Literal['circular', 'force'] | None = Field(default=None)

class EchartsParallel_CoordinatesProperties(GeneratedProperties):
    """echarts / Parallel Coordinates. channels: color, detail"""
    pass

class EchartsPie_ChartProperties(GeneratedProperties):
    """echarts / Pie Chart. channels: size, color, column, row"""
    innerRadius: float | None = Field(default=0, json_schema_extra={'min': 0, 'max': 60, 'step': 5})
    cornerRadius: float | None = Field(default=0, json_schema_extra={'min': 0, 'max': 10, 'step': 1})
    sortSlices: Literal['none', 'descending', 'ascending'] | None = Field(default='none')
    labelType: Literal['categoryPercent', 'category', 'value', 'percent', 'none'] | None = Field(default='categoryPercent')

class EchartsPyramid_ChartProperties(GeneratedProperties):
    """echarts / Pyramid Chart. channels: x, y, color"""
    pass

class EchartsRadar_ChartProperties(GeneratedProperties):
    """echarts / Radar Chart. channels: x, y, color, column, row"""
    shape: Literal['circle'] | None = Field(default=None)
    filled: list[object] | None = Field(default=None)
    fillOpacity: float | None = Field(default=0.3, json_schema_extra={'min': 0.05, 'max': 0.8, 'step': 0.05})

class EchartsRange_Area_ChartProperties(GeneratedProperties):
    """echarts / Range Area Chart. channels: x, y, y2, color, column, row"""
    pass

class EchartsRanged_Dot_PlotProperties(GeneratedProperties):
    """echarts / Ranged Dot Plot. channels: x, y, color"""
    pass

class EchartsRegressionProperties(GeneratedProperties):
    """echarts / Regression. channels: x, y, size, color, column, row"""
    regressionMethod: Literal['linear', 'log', 'exp', 'pow', 'quad', 'poly'] | None = Field(default='linear')
    polyOrder: float | None = Field(default=3, json_schema_extra={'min': 2, 'max': 10, 'step': 1})

class EchartsRose_ChartProperties(GeneratedProperties):
    """echarts / Rose Chart. channels: x, y, color, column, row"""
    alignment: Literal['left', 'center'] | None = Field(default=None)
    sortSlices: Literal['none', 'descending', 'ascending'] | None = Field(default='none')

class EchartsSankey_DiagramProperties(GeneratedProperties):
    """echarts / Sankey Diagram. channels: x, y, size"""
    orient: Literal['horizontal', 'vertical'] | None = Field(default=None)
    nodeWidth: float | None = Field(default=20, json_schema_extra={'min': 5, 'max': 40, 'step': 5})
    nodeGap: float | None = Field(default=10, json_schema_extra={'min': 2, 'max': 30, 'step': 2})

class EchartsScatter_PlotProperties(GeneratedProperties):
    """echarts / Scatter Plot. channels: x, y, color, size, opacity, column, row"""
    opacity: float | None = Field(default=1, json_schema_extra={'min': 0.1, 'max': 1, 'step': 0.05})

class EchartsSlope_ChartProperties(GeneratedProperties):
    """echarts / Slope Chart. channels: x, y, color, detail, column, row"""
    pass

class EchartsStacked_Bar_ChartProperties(GeneratedProperties):
    """echarts / Stacked Bar Chart. channels: x, y, color, column, row"""
    stackMode: Literal['normalize'] | None = Field(default=None)  # data-dependent: check() runs client-side
    sort: Literal['value-desc', 'value-asc'] | None = Field(default=None)  # data-dependent: check() runs client-side

class EchartsStreamgraphProperties(GeneratedProperties):
    """echarts / Streamgraph. channels: x, y, color, column, row"""
    pass

class EchartsStrip_PlotProperties(GeneratedProperties):
    """echarts / Strip Plot. channels: x, y, color, size, column, row"""
    pass

class EchartsSunburst_ChartProperties(GeneratedProperties):
    """echarts / Sunburst Chart. channels: color, size, detail, group"""
    innerRadius: float | None = Field(default=0, json_schema_extra={'min': 0, 'max': 80, 'step': 5})
    labelRotate: list[object] | None = Field(default=None)

class EchartsTreeProperties(GeneratedProperties):
    """echarts / Tree. channels: color, detail, size"""
    orient: Literal['LR', 'TB'] | None = Field(default=None)

class EchartsTreemapProperties(GeneratedProperties):
    """echarts / Treemap. channels: color, size, detail"""
    breadcrumb: list[object] | None = Field(default=None)

class EchartsWaterfall_ChartProperties(GeneratedProperties):
    """echarts / Waterfall Chart. channels: x, y, color, column, row"""
    pass

class ExcelArea_ChartProperties(GeneratedProperties):
    """excel / Area Chart. channels: x, y, color"""
    pass

class ExcelBar_ChartProperties(GeneratedProperties):
    """excel / Bar Chart. channels: x, y, color"""
    pass

class ExcelBoxplotProperties(GeneratedProperties):
    """excel / Boxplot. channels: x, y, color"""
    pass

class ExcelCandlestick_ChartProperties(GeneratedProperties):
    """excel / Candlestick Chart. channels: x, open, high, low, close"""
    pass

class ExcelConnected_Scatter_PlotProperties(GeneratedProperties):
    """excel / Connected Scatter Plot. channels: x, y, order, color, detail"""
    pass

class ExcelDonut_ChartProperties(GeneratedProperties):
    """excel / Donut Chart. channels: color, size, theta"""
    pass

class ExcelFunnel_ChartProperties(GeneratedProperties):
    """excel / Funnel Chart. channels: y, size"""
    pass

class ExcelGrouped_Bar_ChartProperties(GeneratedProperties):
    """excel / Grouped Bar Chart. channels: x, y, group"""
    pass

class ExcelHistogramProperties(GeneratedProperties):
    """excel / Histogram. channels: x, color"""
    pass

class ExcelLine_ChartProperties(GeneratedProperties):
    """excel / Line Chart. channels: x, y, color, strokeDash"""
    pass

class ExcelPie_ChartProperties(GeneratedProperties):
    """excel / Pie Chart. channels: color, size, theta"""
    pass

class ExcelPyramid_ChartProperties(GeneratedProperties):
    """excel / Pyramid Chart. channels: x, y, color"""
    pass

class ExcelRadar_ChartProperties(GeneratedProperties):
    """excel / Radar Chart. channels: x, y, color"""
    pass

class ExcelScatter_PlotProperties(GeneratedProperties):
    """excel / Scatter Plot. channels: x, y, color, size"""
    pass

class ExcelStacked_Bar_ChartProperties(GeneratedProperties):
    """excel / Stacked Bar Chart. channels: x, y, color"""
    pass

class ExcelSunburst_ChartProperties(GeneratedProperties):
    """excel / Sunburst Chart. channels: color, size, group, detail"""
    pass

class ExcelTreemapProperties(GeneratedProperties):
    """excel / Treemap. channels: color, size, detail"""
    pass

class ExcelWaterfall_ChartProperties(GeneratedProperties):
    """excel / Waterfall Chart. channels: x, y, color"""
    pass

class PlotlyArea_ChartProperties(GeneratedProperties):
    """plotly / Area Chart. channels: x, y, color, opacity, column, row"""
    interpolate: Literal['linear', 'monotone', 'step', 'step-before', 'step-after', 'basis', 'cardinal', 'catmull-rom'] | None = Field(default=None)
    opacity: float | None = Field(default=0.4, json_schema_extra={'min': 0.1, 'max': 1, 'step': 0.05})
    stackMode: Literal['normalize', 'layered'] | None = Field(default=None)  # data-dependent: check() runs client-side

class PlotlyBar_ChartProperties(GeneratedProperties):
    """plotly / Bar Chart. channels: x, y, color, opacity, column, row"""
    cornerRadius: float | None = Field(default=0, json_schema_extra={'min': 0, 'max': 15, 'step': 1})
    sort: Literal['value-desc', 'value-asc'] | None = Field(default=None)  # data-dependent: check() runs client-side

class PlotlyBar_TableProperties(GeneratedProperties):
    """plotly / Bar Table. channels: y, x, color, column, row"""
    maxRows: float | None = Field(default=20, json_schema_extra={'min': 5, 'max': 100, 'step': 1})
    showPercent: bool | None = Field(default=False)  # data-dependent: check() runs client-side

class PlotlyBoxplotProperties(GeneratedProperties):
    """plotly / Boxplot. channels: x, y, color, column, row"""
    showPoints: bool | None = Field(default=False)  # data-dependent: check() runs client-side
    showOutliers: bool | None = Field(default=True)  # data-dependent: check() runs client-side

class PlotlyBullet_ChartProperties(GeneratedProperties):
    """plotly / Bullet Chart. channels: y, x, goal, color, column, row"""
    pass

class PlotlyBump_ChartProperties(GeneratedProperties):
    """plotly / Bump Chart. channels: x, y, color, detail, column, row"""
    pass

class PlotlyCandlestick_ChartProperties(GeneratedProperties):
    """plotly / Candlestick Chart. channels: x, open, high, low, close, column, row"""
    showMA: bool | None = Field(default=False)
    maWindow: float | None = Field(default=5, json_schema_extra={'min': 3, 'max': 30, 'step': 1})

class PlotlyChoroplethProperties(GeneratedProperties):
    """plotly / Choropleth. channels: id, color, detail"""
    region: Literal['auto', 'us', 'world'] | None = Field(default='auto')

class PlotlyConnected_Scatter_PlotProperties(GeneratedProperties):
    """plotly / Connected Scatter Plot. channels: x, y, order, color, detail, column, row"""
    pass

class PlotlyDensity_ContourProperties(GeneratedProperties):
    """plotly / Density Contour. channels: x, y, column, row"""
    binCount: float | None = Field(default=20, json_schema_extra={'min': 5, 'max': 50, 'step': 1})
    showPoints: bool | None = Field(default=True)
    colorScheme: Literal['viridis', 'inferno', 'magma', 'plasma', 'turbo', 'greens', 'reds'] | None = Field(default=None)  # data-dependent: check() runs client-side

class PlotlyDensity_PlotProperties(GeneratedProperties):
    """plotly / Density Plot. channels: x, color, column, row"""
    bandwidth: float | None = Field(default=0, json_schema_extra={'min': 0.05, 'max': 2, 'step': 0.05})

class PlotlyDonut_ChartProperties(GeneratedProperties):
    """plotly / Donut Chart. channels: size, color"""
    innerRadius: float | None = Field(default=55, json_schema_extra={'min': 20, 'max': 80, 'step': 5})
    sortSlices: Literal['none', 'descending', 'ascending'] | None = Field(default='none')
    labelType: Literal['categoryPercent', 'category', 'value', 'percent', 'none'] | None = Field(default='categoryPercent')

class PlotlyECDF_PlotProperties(GeneratedProperties):
    """plotly / ECDF Plot. channels: x, color, detail, column, row"""
    showPoints: bool | None = Field(default=False)

class PlotlyFunnel_ChartProperties(GeneratedProperties):
    """plotly / Funnel Chart. channels: y, size"""
    sort: Literal['descending', 'ascending', 'none'] | None = Field(default='descending')

class PlotlyGantt_ChartProperties(GeneratedProperties):
    """plotly / Gantt Chart. channels: y, x, x2, color, detail, column, row"""
    taskHeight: float | None = Field(default=70, json_schema_extra={'min': 40, 'max': 90, 'step': 5})
    cornerRadius: float | None = Field(default=2, json_schema_extra={'min': 0, 'max': 8, 'step': 1})
    intervalLabels: bool | None = Field(default=False)

class PlotlyGauge_ChartProperties(GeneratedProperties):
    """plotly / Gauge Chart. channels: size, column"""
    min: float | None = Field(default=0, json_schema_extra={'min': 0, 'max': 1000, 'step': 10})
    max: float | None = Field(default=100, json_schema_extra={'min': 0, 'max': 10000, 'step': 100})

class PlotlyGrouped_Bar_ChartProperties(GeneratedProperties):
    """plotly / Grouped Bar Chart. channels: x, y, group, color, column, row"""
    sort: Literal['value-desc', 'value-asc'] | None = Field(default=None)  # data-dependent: check() runs client-side

class PlotlyHeatmapProperties(GeneratedProperties):
    """plotly / Heatmap. channels: x, y, color, column, row"""
    colorScheme: Literal['viridis', 'inferno', 'magma', 'plasma', 'turbo', 'blues', 'reds', 'greens', 'oranges', 'purples', 'greys', 'blueorange', 'redblue'] | None = Field(default=None)  # data-dependent: check() runs client-side

class PlotlyHistogramProperties(GeneratedProperties):
    """plotly / Histogram. channels: x, color, column, row"""
    binCount: float | None = Field(default=10, json_schema_extra={'min': 5, 'max': 50, 'step': 1})

class PlotlyKPI_CardProperties(GeneratedProperties):
    """plotly / KPI Card. channels: metric, value, goal"""
    layout: Literal['horizontal', 'vertical', 'grid'] | None = Field(default=None)

class PlotlyLine_ChartProperties(GeneratedProperties):
    """plotly / Line Chart. channels: x, y, color, strokeDash, opacity, column, row"""
    interpolate: Literal['linear', 'monotone', 'step', 'step-before', 'step-after', 'basis', 'cardinal', 'catmull-rom'] | None = Field(default=None)
    showPoints: bool | None = Field(default=False)

class PlotlyLollipop_ChartProperties(GeneratedProperties):
    """plotly / Lollipop Chart. channels: x, y, color, column, row"""
    dotSize: float | None = Field(default=80, json_schema_extra={'min': 20, 'max': 300, 'step': 10})
    sort: Literal['value-desc', 'value-asc'] | None = Field(default=None)  # data-dependent: check() runs client-side

class PlotlyMapProperties(GeneratedProperties):
    """plotly / Map. channels: longitude, latitude, color, size, opacity"""
    region: Literal['auto', 'us', 'world'] | None = Field(default='auto')
    projection: Literal['default', 'mercator', 'equalEarth', 'orthographic', 'stereographic', 'conicEqualArea', 'conicEquidistant', 'azimuthalEquidistant', 'mollweide'] | None = Field(default='default')  # data-dependent: check() runs client-side
    projectionCenter: list[object] | None = Field(default=None)  # data-dependent: check() runs client-side

class PlotlyPie_ChartProperties(GeneratedProperties):
    """plotly / Pie Chart. channels: size, color"""
    sortSlices: Literal['none', 'descending', 'ascending'] | None = Field(default='none')
    labelType: Literal['categoryPercent', 'category', 'value', 'percent', 'none'] | None = Field(default='categoryPercent')

class PlotlyPyramid_ChartProperties(GeneratedProperties):
    """plotly / Pyramid Chart. channels: x, y, color"""
    pass

class PlotlyRadar_ChartProperties(GeneratedProperties):
    """plotly / Radar Chart. channels: x, y, color, column, row"""
    filled: list[object] | None = Field(default=None)
    fillOpacity: float | None = Field(default=0.16, json_schema_extra={'min': 0.05, 'max': 0.8, 'step': 0.05})

class PlotlyRange_Area_ChartProperties(GeneratedProperties):
    """plotly / Range Area Chart. channels: x, y, y2, color, column, row"""
    opacity: float | None = Field(default=0.35, json_schema_extra={'min': 0.1, 'max': 1, 'step': 0.05})

class PlotlyRanged_Dot_PlotProperties(GeneratedProperties):
    """plotly / Ranged Dot Plot. channels: x, y, color"""
    pass

class PlotlyRegressionProperties(GeneratedProperties):
    """plotly / Regression. channels: x, y, size, color, column, row"""
    regressionMethod: Literal['linear', 'log', 'exp', 'pow', 'quad', 'poly'] | None = Field(default='linear')
    polyOrder: float | None = Field(default=3, json_schema_extra={'min': 2, 'max': 10, 'step': 1})
    opacity: float | None = Field(default=1, json_schema_extra={'min': 0.1, 'max': 1, 'step': 0.05})

class PlotlyRose_ChartProperties(GeneratedProperties):
    """plotly / Rose Chart. channels: x, y, color"""
    sortSlices: Literal['none', 'descending', 'ascending'] | None = Field(default='none')

class PlotlyScatter_PlotProperties(GeneratedProperties):
    """plotly / Scatter Plot. channels: x, y, color, size, shape, opacity, column, row"""
    opacity: float | None = Field(default=1, json_schema_extra={'min': 0.1, 'max': 1, 'step': 0.05})

class PlotlySlope_ChartProperties(GeneratedProperties):
    """plotly / Slope Chart. channels: x, y, color, detail, column, row"""
    pass

class PlotlySparklineProperties(GeneratedProperties):
    """plotly / Sparkline. channels: x, y, color, detail"""
    baseline: Literal['mean', 'zero', 'median', 'none'] | None = Field(default='mean')
    trendWidth: float | None = Field(default=240, json_schema_extra={'min': 80, 'max': 600, 'step': 10})

class PlotlyStacked_Bar_ChartProperties(GeneratedProperties):
    """plotly / Stacked Bar Chart. channels: x, y, color, column, row"""
    stackMode: Literal['normalize'] | None = Field(default=None)  # data-dependent: check() runs client-side
    sort: Literal['value-desc', 'value-asc'] | None = Field(default=None)  # data-dependent: check() runs client-side

class PlotlyStreamgraphProperties(GeneratedProperties):
    """plotly / Streamgraph. channels: x, y, color, column, row"""
    pass

class PlotlyStrip_PlotProperties(GeneratedProperties):
    """plotly / Strip Plot. channels: x, y, color, size, column, row"""
    pass

class PlotlyViolin_PlotProperties(GeneratedProperties):
    """plotly / Violin Plot. channels: x, y, color, column, row"""
    showBox: bool | None = Field(default=True)
    showPoints: bool | None = Field(default=False)

class PlotlyWaterfall_ChartProperties(GeneratedProperties):
    """plotly / Waterfall Chart. channels: x, y, color, column, row"""
    totals: Literal['auto', 'none', 'first', 'last', 'both'] | None = Field(default='auto')
    showTextLabels: bool | None = Field(default=False)

class VegaliteArea_ChartProperties(GeneratedProperties):
    """vegalite / Area Chart. channels: x, y, color, opacity, column, row"""
    interpolate: Literal['linear', 'monotone', 'step', 'step-before', 'step-after', 'basis', 'cardinal', 'catmull-rom'] | None = Field(default=None)
    opacity: float | None = Field(default=0.7, json_schema_extra={'min': 0.1, 'max': 1, 'step': 0.1})  # data-dependent: check() runs client-side
    stackMode: Literal['normalize', 'center', 'layered'] | None = Field(default=None)  # data-dependent: check() runs client-side
    independentYAxis: bool | None = Field(default=None)  # data-dependent: check() runs client-side
    xAxisType: Literal['temporal', 'nominal'] | None = Field(default=None)  # data-dependent: check() runs client-side
    yAxisType: Literal['temporal', 'nominal'] | None = Field(default=None)  # data-dependent: check() runs client-side

class VegaliteBar_ChartProperties(GeneratedProperties):
    """vegalite / Bar Chart. channels: x, y, color, opacity, column, row"""
    cornerRadius: float | None = Field(default=0, json_schema_extra={'min': 0, 'max': 15, 'step': 1})
    independentYAxis: bool | None = Field(default=None)  # data-dependent: check() runs client-side
    xAxisType: Literal['temporal', 'nominal'] | None = Field(default=None)  # data-dependent: check() runs client-side
    yAxisType: Literal['temporal', 'nominal'] | None = Field(default=None)  # data-dependent: check() runs client-side
    showValueLabels: bool | None = Field(default=False)  # data-dependent: check() runs client-side
    sort: Literal['value-desc', 'value-asc'] | None = Field(default=None)  # data-dependent: check() runs client-side

class VegaliteBar_TableProperties(GeneratedProperties):
    """vegalite / Bar Table. channels: y, x, color, column, row"""
    maxRows: float | None = Field(default=20, json_schema_extra={'min': 5, 'max': 100, 'step': 1})
    showPercent: bool | None = Field(default=False)  # data-dependent: check() runs client-side
    independentYAxis: bool | None = Field(default=None)  # data-dependent: check() runs client-side

class VegaliteBoxplotProperties(GeneratedProperties):
    """vegalite / Boxplot. channels: x, y, color, opacity, column, row"""
    whiskerMethod: Literal['iqr', 'minmax'] | None = Field(default='iqr')
    showPoints: bool | None = Field(default=False)  # data-dependent: check() runs client-side
    showOutliers: bool | None = Field(default=True)  # data-dependent: check() runs client-side
    dodge: Literal['auto', 'local', 'global'] | None = Field(default='auto')  # data-dependent: check() runs client-side
    independentYAxis: bool | None = Field(default=None)  # data-dependent: check() runs client-side
    logScale_x: bool | None = Field(default=False)  # data-dependent: check() runs client-side
    logScale_y: bool | None = Field(default=False)  # data-dependent: check() runs client-side
    includeZero_x: bool | None = Field(default=None)  # data-dependent: check() runs client-side
    includeZero_y: bool | None = Field(default=None)  # data-dependent: check() runs client-side

class VegaliteBullet_ChartProperties(GeneratedProperties):
    """vegalite / Bullet Chart. channels: y, x, goal, color, column, row"""
    independentYAxis: bool | None = Field(default=None)  # data-dependent: check() runs client-side

class VegaliteBump_ChartProperties(GeneratedProperties):
    """vegalite / Bump Chart. channels: x, y, color, detail, column, row"""
    interpolate: Literal['linear', 'monotone', 'step', 'step-before', 'step-after', 'basis', 'cardinal', 'catmull-rom'] | None = Field(default=None)
    independentYAxis: bool | None = Field(default=None)  # data-dependent: check() runs client-side
    logScale_x: bool | None = Field(default=False)  # data-dependent: check() runs client-side
    logScale_y: bool | None = Field(default=False)  # data-dependent: check() runs client-side
    includeZero_x: bool | None = Field(default=None)  # data-dependent: check() runs client-side
    includeZero_y: bool | None = Field(default=None)  # data-dependent: check() runs client-side

class VegaliteCalendar_HeatmapProperties(GeneratedProperties):
    """vegalite / Calendar Heatmap. channels: x, color"""
    cornerRadius: float | None = Field(default=2, json_schema_extra={'min': 0, 'max': 8, 'step': 1})
    colorScheme: Literal['viridis', 'github', 'blues', 'greens', 'reds', 'oranges', 'purples'] | None = Field(default=None)  # data-dependent: check() runs client-side

class VegaliteCandlestick_ChartProperties(GeneratedProperties):
    """vegalite / Candlestick Chart. channels: x, open, high, low, close, column, row"""
    independentYAxis: bool | None = Field(default=None)  # data-dependent: check() runs client-side
    logScale_x: bool | None = Field(default=False)  # data-dependent: check() runs client-side
    logScale_y: bool | None = Field(default=False)  # data-dependent: check() runs client-side
    includeZero_x: bool | None = Field(default=None)  # data-dependent: check() runs client-side
    includeZero_y: bool | None = Field(default=None)  # data-dependent: check() runs client-side

class VegaliteChoroplethProperties(GeneratedProperties):
    """vegalite / Choropleth. channels: id, color, detail"""
    region: Literal['auto', 'us', 'world'] | None = Field(default='auto')

class VegaliteConnected_Scatter_PlotProperties(GeneratedProperties):
    """vegalite / Connected Scatter Plot. channels: x, y, order, color, detail, column, row"""
    independentYAxis: bool | None = Field(default=None)  # data-dependent: check() runs client-side
    logScale_x: bool | None = Field(default=False)  # data-dependent: check() runs client-side
    logScale_y: bool | None = Field(default=False)  # data-dependent: check() runs client-side
    includeZero_x: bool | None = Field(default=None)  # data-dependent: check() runs client-side
    includeZero_y: bool | None = Field(default=None)  # data-dependent: check() runs client-side

class VegaliteDensity_PlotProperties(GeneratedProperties):
    """vegalite / Density Plot. channels: x, color, column, row"""
    bandwidth: float | None = Field(default=0, json_schema_extra={'min': 0.05, 'max': 2, 'step': 0.05})
    independentYAxis: bool | None = Field(default=None)  # data-dependent: check() runs client-side

class VegaliteDonut_ChartProperties(GeneratedProperties):
    """vegalite / Donut Chart. channels: size, color, column, row"""
    innerRadius: float | None = Field(default=50, json_schema_extra={'min': 0, 'max': 100, 'step': 5})
    sortSlices: Literal['none', 'descending', 'ascending'] | None = Field(default='none')
    independentYAxis: bool | None = Field(default=None)  # data-dependent: check() runs client-side
    showValueLabels: bool | None = Field(default=False)  # data-dependent: check() runs client-side

class VegaliteECDF_PlotProperties(GeneratedProperties):
    """vegalite / ECDF Plot. channels: x, color, detail, column, row"""
    showPoints: bool | None = Field(default=False)
    independentYAxis: bool | None = Field(default=None)  # data-dependent: check() runs client-side
    logScale_x: bool | None = Field(default=False)  # data-dependent: check() runs client-side
    logScale_y: bool | None = Field(default=False)  # data-dependent: check() runs client-side
    includeZero_x: bool | None = Field(default=None)  # data-dependent: check() runs client-side
    includeZero_y: bool | None = Field(default=None)  # data-dependent: check() runs client-side

class VegaliteGantt_ChartProperties(GeneratedProperties):
    """vegalite / Gantt Chart. channels: y, x, x2, color, detail, column, row"""
    taskHeight: float | None = Field(default=70, json_schema_extra={'min': 40, 'max': 90, 'step': 5})
    cornerRadius: float | None = Field(default=2, json_schema_extra={'min': 0, 'max': 8, 'step': 1})
    intervalLabels: bool | None = Field(default=False)
    independentYAxis: bool | None = Field(default=None)  # data-dependent: check() runs client-side
    logScale_x: bool | None = Field(default=False)  # data-dependent: check() runs client-side
    logScale_y: bool | None = Field(default=False)  # data-dependent: check() runs client-side
    includeZero_x: bool | None = Field(default=None)  # data-dependent: check() runs client-side
    includeZero_y: bool | None = Field(default=None)  # data-dependent: check() runs client-side

class VegaliteGrouped_Bar_ChartProperties(GeneratedProperties):
    """vegalite / Grouped Bar Chart. channels: x, y, group, column, row"""
    dodge: Literal['auto', 'local', 'global'] | None = Field(default='auto')  # data-dependent: check() runs client-side
    independentYAxis: bool | None = Field(default=None)  # data-dependent: check() runs client-side
    showValueLabels: bool | None = Field(default=False)  # data-dependent: check() runs client-side
    sort: Literal['value-desc', 'value-asc'] | None = Field(default=None)  # data-dependent: check() runs client-side

class VegaliteHeatmapProperties(GeneratedProperties):
    """vegalite / Heatmap. channels: x, y, color, column, row"""
    showValueLabels: bool | None = Field(default=False)
    independentYAxis: bool | None = Field(default=None)  # data-dependent: check() runs client-side
    xAxisType: Literal['temporal', 'nominal'] | None = Field(default=None)  # data-dependent: check() runs client-side
    yAxisType: Literal['temporal', 'nominal'] | None = Field(default=None)  # data-dependent: check() runs client-side
    colorScheme: Literal['viridis', 'inferno', 'magma', 'plasma', 'turbo', 'blues', 'reds', 'greens', 'oranges', 'purples', 'greys', 'blueorange', 'redblue'] | None = Field(default=None)  # data-dependent: check() runs client-side

class VegaliteHistogramProperties(GeneratedProperties):
    """vegalite / Histogram. channels: x, color, column, row"""
    binCount: float | None = Field(default=0, json_schema_extra={'min': 5, 'max': 50, 'step': 1})
    independentYAxis: bool | None = Field(default=None)  # data-dependent: check() runs client-side

class VegaliteKPI_CardProperties(GeneratedProperties):
    """vegalite / KPI Card. channels: metric, value, goal"""
    layout: Literal['horizontal', 'vertical', 'grid'] | None = Field(default='grid')
    style: bool | None = Field(default=True)
    behindThreshold: float | None = Field(default=0.5, json_schema_extra={'min': 0, 'max': 1, 'step': 0.05})  # data-dependent: check() runs client-side
    logScale_x: bool | None = Field(default=False)  # data-dependent: check() runs client-side
    logScale_y: bool | None = Field(default=False)  # data-dependent: check() runs client-side
    includeZero_x: bool | None = Field(default=None)  # data-dependent: check() runs client-side
    includeZero_y: bool | None = Field(default=None)  # data-dependent: check() runs client-side

class VegaliteLine_ChartProperties(GeneratedProperties):
    """vegalite / Line Chart. channels: x, y, color, strokeDash, detail, opacity, column, row"""
    interpolate: Literal['linear', 'monotone', 'step', 'step-before', 'step-after', 'basis', 'cardinal', 'catmull-rom'] | None = Field(default=None)
    showPoints: bool | None = Field(default=False)
    independentYAxis: bool | None = Field(default=None)  # data-dependent: check() runs client-side
    logScale_x: bool | None = Field(default=False)  # data-dependent: check() runs client-side
    logScale_y: bool | None = Field(default=False)  # data-dependent: check() runs client-side
    includeZero_x: bool | None = Field(default=None)  # data-dependent: check() runs client-side
    includeZero_y: bool | None = Field(default=None)  # data-dependent: check() runs client-side
    xAxisType: Literal['temporal', 'nominal'] | None = Field(default=None)  # data-dependent: check() runs client-side
    yAxisType: Literal['temporal', 'nominal'] | None = Field(default=None)  # data-dependent: check() runs client-side

class VegaliteLollipop_ChartProperties(GeneratedProperties):
    """vegalite / Lollipop Chart. channels: x, y, color, column, row"""
    dotSize: float | None = Field(default=80, json_schema_extra={'min': 20, 'max': 300, 'step': 10})
    independentYAxis: bool | None = Field(default=None)  # data-dependent: check() runs client-side
    xAxisType: Literal['temporal', 'nominal'] | None = Field(default=None)  # data-dependent: check() runs client-side
    yAxisType: Literal['temporal', 'nominal'] | None = Field(default=None)  # data-dependent: check() runs client-side
    showValueLabels: bool | None = Field(default=False)  # data-dependent: check() runs client-side
    sort: Literal['value-desc', 'value-asc'] | None = Field(default=None)  # data-dependent: check() runs client-side

class VegaliteMapProperties(GeneratedProperties):
    """vegalite / Map. channels: longitude, latitude, color, size, opacity"""
    region: Literal['auto', 'us', 'world'] | None = Field(default='auto')
    projection: Literal['default', 'mercator', 'equalEarth', 'orthographic', 'stereographic', 'conicEqualArea', 'conicEquidistant', 'azimuthalEquidistant', 'mollweide'] | None = Field(default='default')  # data-dependent: check() runs client-side
    projectionCenter: list[object] | None = Field(default=None)  # data-dependent: check() runs client-side
    logScale_x: bool | None = Field(default=False)  # data-dependent: check() runs client-side
    logScale_y: bool | None = Field(default=False)  # data-dependent: check() runs client-side
    includeZero_x: bool | None = Field(default=None)  # data-dependent: check() runs client-side
    includeZero_y: bool | None = Field(default=None)  # data-dependent: check() runs client-side

class VegalitePie_ChartProperties(GeneratedProperties):
    """vegalite / Pie Chart. channels: size, color, column, row"""
    innerRadius: float | None = Field(default=0, json_schema_extra={'min': 0, 'max': 100, 'step': 5})
    sortSlices: Literal['none', 'descending', 'ascending'] | None = Field(default='none')
    independentYAxis: bool | None = Field(default=None)  # data-dependent: check() runs client-side
    showValueLabels: bool | None = Field(default=False)  # data-dependent: check() runs client-side

class VegalitePyramid_ChartProperties(GeneratedProperties):
    """vegalite / Pyramid Chart. channels: x, y, color"""
    showValueLabels: bool | None = Field(default=False)  # data-dependent: check() runs client-side

class VegaliteRadar_ChartProperties(GeneratedProperties):
    """vegalite / Radar Chart. channels: x, y, color, column, row"""
    filled: bool | None = Field(default=True)
    fillOpacity: float | None = Field(default=0.15, json_schema_extra={'min': 0, 'max': 0.5, 'step': 0.1})
    strokeWidth: float | None = Field(default=1.5, json_schema_extra={'min': 0.5, 'max': 4, 'step': 0.5})
    independentYAxis: bool | None = Field(default=None)  # data-dependent: check() runs client-side
    logScale_x: bool | None = Field(default=False)  # data-dependent: check() runs client-side
    logScale_y: bool | None = Field(default=False)  # data-dependent: check() runs client-side
    includeZero_x: bool | None = Field(default=None)  # data-dependent: check() runs client-side
    includeZero_y: bool | None = Field(default=None)  # data-dependent: check() runs client-side

class VegaliteRange_Area_ChartProperties(GeneratedProperties):
    """vegalite / Range Area Chart. channels: x, y, y2, color, column, row"""
    interpolate: Literal['linear', 'monotone', 'step', 'step-before', 'step-after', 'basis'] | None = Field(default=None)
    opacity: float | None = Field(default=0.5, json_schema_extra={'min': 0.1, 'max': 1, 'step': 0.1})
    independentYAxis: bool | None = Field(default=None)  # data-dependent: check() runs client-side

class VegaliteRanged_Dot_PlotProperties(GeneratedProperties):
    """vegalite / Ranged Dot Plot. channels: x, y, color"""
    logScale_x: bool | None = Field(default=False)  # data-dependent: check() runs client-side
    logScale_y: bool | None = Field(default=False)  # data-dependent: check() runs client-side
    includeZero_x: bool | None = Field(default=None)  # data-dependent: check() runs client-side
    includeZero_y: bool | None = Field(default=None)  # data-dependent: check() runs client-side

class VegaliteRegressionProperties(GeneratedProperties):
    """vegalite / Regression. channels: x, y, size, color, column, row"""
    regressionMethod: Literal['linear', 'log', 'exp', 'pow', 'quad', 'poly'] | None = Field(default='linear')
    polyOrder: float | None = Field(default=3, json_schema_extra={'min': 2, 'max': 10, 'step': 1})
    independentYAxis: bool | None = Field(default=None)  # data-dependent: check() runs client-side
    logScale_x: bool | None = Field(default=False)  # data-dependent: check() runs client-side
    logScale_y: bool | None = Field(default=False)  # data-dependent: check() runs client-side
    includeZero_x: bool | None = Field(default=None)  # data-dependent: check() runs client-side
    includeZero_y: bool | None = Field(default=None)  # data-dependent: check() runs client-side

class VegaliteRose_ChartProperties(GeneratedProperties):
    """vegalite / Rose Chart. channels: x, y, color, column, row"""
    padAngle: float | None = Field(default=0, json_schema_extra={'min': 0, 'max': 0.1, 'step': 0.005})
    alignment: Literal['left', 'center'] | None = Field(default=None)
    sortSlices: Literal['none', 'descending', 'ascending'] | None = Field(default='none')
    independentYAxis: bool | None = Field(default=None)  # data-dependent: check() runs client-side
    showValueLabels: bool | None = Field(default=False)  # data-dependent: check() runs client-side

class VegaliteScatter_PlotProperties(GeneratedProperties):
    """vegalite / Scatter Plot. channels: x, y, color, size, shape, opacity, column, row"""
    opacity: float | None = Field(default=1, json_schema_extra={'min': 0.1, 'max': 1, 'step': 0.1})
    independentYAxis: bool | None = Field(default=None)  # data-dependent: check() runs client-side
    logScale_x: bool | None = Field(default=False)  # data-dependent: check() runs client-side
    logScale_y: bool | None = Field(default=False)  # data-dependent: check() runs client-side
    includeZero_x: bool | None = Field(default=None)  # data-dependent: check() runs client-side
    includeZero_y: bool | None = Field(default=None)  # data-dependent: check() runs client-side

class VegaliteSlope_ChartProperties(GeneratedProperties):
    """vegalite / Slope Chart. channels: x, y, color, detail, column, row"""
    showText: bool | None = Field(default=False)
    showSeriesInLabel: bool | None = Field(default=False)  # data-dependent: check() runs client-side
    independentYAxis: bool | None = Field(default=None)  # data-dependent: check() runs client-side
    logScale_x: bool | None = Field(default=False)  # data-dependent: check() runs client-side
    logScale_y: bool | None = Field(default=False)  # data-dependent: check() runs client-side
    includeZero_x: bool | None = Field(default=None)  # data-dependent: check() runs client-side
    includeZero_y: bool | None = Field(default=None)  # data-dependent: check() runs client-side

class VegaliteSparklineProperties(GeneratedProperties):
    """vegalite / Sparkline. channels: x, y, color, detail, row, column"""
    interpolate: Literal['linear', 'monotone', 'step', 'step-before', 'step-after', 'basis', 'cardinal', 'catmull-rom'] | None = Field(default=None)
    baseline: Literal['mean', 'zero', 'median', 'none'] | None = Field(default='mean')
    trendWidth: float | None = Field(default=240, json_schema_extra={'min': 80, 'max': 600, 'step': 10})
    logScale_x: bool | None = Field(default=False)  # data-dependent: check() runs client-side
    logScale_y: bool | None = Field(default=False)  # data-dependent: check() runs client-side
    includeZero_x: bool | None = Field(default=None)  # data-dependent: check() runs client-side
    includeZero_y: bool | None = Field(default=None)  # data-dependent: check() runs client-side

class VegaliteStacked_Bar_ChartProperties(GeneratedProperties):
    """vegalite / Stacked Bar Chart. channels: x, y, color, column, row"""
    stackMode: Literal['normalize', 'center'] | None = Field(default=None)  # data-dependent: check() runs client-side
    independentYAxis: bool | None = Field(default=None)  # data-dependent: check() runs client-side
    showValueLabels: bool | None = Field(default=False)  # data-dependent: check() runs client-side
    sort: Literal['value-desc', 'value-asc'] | None = Field(default=None)  # data-dependent: check() runs client-side

class VegaliteStreamgraphProperties(GeneratedProperties):
    """vegalite / Streamgraph. channels: x, y, color, column, row"""
    interpolate: Literal['linear', 'monotone', 'step', 'step-before', 'step-after', 'basis', 'cardinal', 'catmull-rom'] | None = Field(default=None)
    independentYAxis: bool | None = Field(default=None)  # data-dependent: check() runs client-side

class VegaliteStrip_PlotProperties(GeneratedProperties):
    """vegalite / Strip Plot. channels: x, y, color, size, column, row"""
    stepWidth: float | None = Field(default=20, json_schema_extra={'min': 10, 'max': 100, 'step': 5})
    pointSize: float | None = Field(default=0, json_schema_extra={'min': 0, 'max': 150, 'step': 5})
    opacity: float | None = Field(default=0, json_schema_extra={'min': 0, 'max': 1, 'step': 0.1})
    independentYAxis: bool | None = Field(default=None)  # data-dependent: check() runs client-side
    logScale_x: bool | None = Field(default=False)  # data-dependent: check() runs client-side
    logScale_y: bool | None = Field(default=False)  # data-dependent: check() runs client-side
    includeZero_x: bool | None = Field(default=None)  # data-dependent: check() runs client-side
    includeZero_y: bool | None = Field(default=None)  # data-dependent: check() runs client-side

class VegaliteViolin_PlotProperties(GeneratedProperties):
    """vegalite / Violin Plot. channels: x, y, color, row"""
    bandwidth: float | None = Field(default=0, json_schema_extra={'min': 0.05, 'max': 2, 'step': 0.05})
    showPoints: bool | None = Field(default=False)
    showMedian: bool | None = Field(default=False)
    showContour: bool | None = Field(default=False)
    medianWidth: float | None = Field(default=0.6, json_schema_extra={'min': 0.2, 'max': 1, 'step': 0.05})  # data-dependent: check() runs client-side
    independentYAxis: bool | None = Field(default=None)  # data-dependent: check() runs client-side

class VegaliteWaterfall_ChartProperties(GeneratedProperties):
    """vegalite / Waterfall Chart. channels: x, y, color, column, row"""
    cornerRadius: float | None = Field(default=0, json_schema_extra={'min': 0, 'max': 8, 'step': 1})
    totals: Literal['auto', 'none', 'first', 'last', 'both'] | None = Field(default='auto')  # data-dependent: check() runs client-side
    showValueLabels: bool | None = Field(default=False)
    independentYAxis: bool | None = Field(default=None)  # data-dependent: check() runs client-side

__all__ = [
    'FLINT_VERSION',
    'BUNDLE_SHA256',
    'CHART_TYPES',
    'CHANNELS',
    'SEMANTIC_TYPES',
    'THEME_PRESETS',
    'ChartType',
    'SemanticTypeName',
    'ThemePresetName',
    'GeneratedProperties',
    'ChartjsArea_ChartProperties',
    'ChartjsBar_ChartProperties',
    'ChartjsBubble_ChartProperties',
    'ChartjsBump_ChartProperties',
    'ChartjsCombo_ChartProperties',
    'ChartjsConnected_Scatter_PlotProperties',
    'ChartjsDoughnut_ChartProperties',
    'ChartjsECDF_PlotProperties',
    'ChartjsGantt_ChartProperties',
    'ChartjsGrouped_Bar_ChartProperties',
    'ChartjsHistogramProperties',
    'ChartjsLine_ChartProperties',
    'ChartjsLollipop_ChartProperties',
    'ChartjsPie_ChartProperties',
    'ChartjsRadar_ChartProperties',
    'ChartjsRange_Area_ChartProperties',
    'ChartjsRose_ChartProperties',
    'ChartjsScatter_PlotProperties',
    'ChartjsSlope_ChartProperties',
    'ChartjsStacked_Bar_ChartProperties',
    'ChartjsStrip_PlotProperties',
    'ChartjsWaterfall_ChartProperties',
    'EchartsArea_ChartProperties',
    'EchartsBar_ChartProperties',
    'EchartsBoxplotProperties',
    'EchartsBullet_ChartProperties',
    'EchartsBump_ChartProperties',
    'EchartsCalendar_HeatmapProperties',
    'EchartsCandlestick_ChartProperties',
    'EchartsConnected_Scatter_PlotProperties',
    'EchartsDensity_PlotProperties',
    'EchartsECDF_PlotProperties',
    'EchartsFunnel_ChartProperties',
    'EchartsGantt_ChartProperties',
    'EchartsGauge_ChartProperties',
    'EchartsGrouped_Bar_ChartProperties',
    'EchartsHeatmapProperties',
    'EchartsHistogramProperties',
    'EchartsLine_ChartProperties',
    'EchartsLollipop_ChartProperties',
    'EchartsNetwork_GraphProperties',
    'EchartsParallel_CoordinatesProperties',
    'EchartsPie_ChartProperties',
    'EchartsPyramid_ChartProperties',
    'EchartsRadar_ChartProperties',
    'EchartsRange_Area_ChartProperties',
    'EchartsRanged_Dot_PlotProperties',
    'EchartsRegressionProperties',
    'EchartsRose_ChartProperties',
    'EchartsSankey_DiagramProperties',
    'EchartsScatter_PlotProperties',
    'EchartsSlope_ChartProperties',
    'EchartsStacked_Bar_ChartProperties',
    'EchartsStreamgraphProperties',
    'EchartsStrip_PlotProperties',
    'EchartsSunburst_ChartProperties',
    'EchartsTreeProperties',
    'EchartsTreemapProperties',
    'EchartsWaterfall_ChartProperties',
    'ExcelArea_ChartProperties',
    'ExcelBar_ChartProperties',
    'ExcelBoxplotProperties',
    'ExcelCandlestick_ChartProperties',
    'ExcelConnected_Scatter_PlotProperties',
    'ExcelDonut_ChartProperties',
    'ExcelFunnel_ChartProperties',
    'ExcelGrouped_Bar_ChartProperties',
    'ExcelHistogramProperties',
    'ExcelLine_ChartProperties',
    'ExcelPie_ChartProperties',
    'ExcelPyramid_ChartProperties',
    'ExcelRadar_ChartProperties',
    'ExcelScatter_PlotProperties',
    'ExcelStacked_Bar_ChartProperties',
    'ExcelSunburst_ChartProperties',
    'ExcelTreemapProperties',
    'ExcelWaterfall_ChartProperties',
    'PlotlyArea_ChartProperties',
    'PlotlyBar_ChartProperties',
    'PlotlyBar_TableProperties',
    'PlotlyBoxplotProperties',
    'PlotlyBullet_ChartProperties',
    'PlotlyBump_ChartProperties',
    'PlotlyCandlestick_ChartProperties',
    'PlotlyChoroplethProperties',
    'PlotlyConnected_Scatter_PlotProperties',
    'PlotlyDensity_ContourProperties',
    'PlotlyDensity_PlotProperties',
    'PlotlyDonut_ChartProperties',
    'PlotlyECDF_PlotProperties',
    'PlotlyFunnel_ChartProperties',
    'PlotlyGantt_ChartProperties',
    'PlotlyGauge_ChartProperties',
    'PlotlyGrouped_Bar_ChartProperties',
    'PlotlyHeatmapProperties',
    'PlotlyHistogramProperties',
    'PlotlyKPI_CardProperties',
    'PlotlyLine_ChartProperties',
    'PlotlyLollipop_ChartProperties',
    'PlotlyMapProperties',
    'PlotlyPie_ChartProperties',
    'PlotlyPyramid_ChartProperties',
    'PlotlyRadar_ChartProperties',
    'PlotlyRange_Area_ChartProperties',
    'PlotlyRanged_Dot_PlotProperties',
    'PlotlyRegressionProperties',
    'PlotlyRose_ChartProperties',
    'PlotlyScatter_PlotProperties',
    'PlotlySlope_ChartProperties',
    'PlotlySparklineProperties',
    'PlotlyStacked_Bar_ChartProperties',
    'PlotlyStreamgraphProperties',
    'PlotlyStrip_PlotProperties',
    'PlotlyViolin_PlotProperties',
    'PlotlyWaterfall_ChartProperties',
    'VegaliteArea_ChartProperties',
    'VegaliteBar_ChartProperties',
    'VegaliteBar_TableProperties',
    'VegaliteBoxplotProperties',
    'VegaliteBullet_ChartProperties',
    'VegaliteBump_ChartProperties',
    'VegaliteCalendar_HeatmapProperties',
    'VegaliteCandlestick_ChartProperties',
    'VegaliteChoroplethProperties',
    'VegaliteConnected_Scatter_PlotProperties',
    'VegaliteDensity_PlotProperties',
    'VegaliteDonut_ChartProperties',
    'VegaliteECDF_PlotProperties',
    'VegaliteGantt_ChartProperties',
    'VegaliteGrouped_Bar_ChartProperties',
    'VegaliteHeatmapProperties',
    'VegaliteHistogramProperties',
    'VegaliteKPI_CardProperties',
    'VegaliteLine_ChartProperties',
    'VegaliteLollipop_ChartProperties',
    'VegaliteMapProperties',
    'VegalitePie_ChartProperties',
    'VegalitePyramid_ChartProperties',
    'VegaliteRadar_ChartProperties',
    'VegaliteRange_Area_ChartProperties',
    'VegaliteRanged_Dot_PlotProperties',
    'VegaliteRegressionProperties',
    'VegaliteRose_ChartProperties',
    'VegaliteScatter_PlotProperties',
    'VegaliteSlope_ChartProperties',
    'VegaliteSparklineProperties',
    'VegaliteStacked_Bar_ChartProperties',
    'VegaliteStreamgraphProperties',
    'VegaliteStrip_PlotProperties',
    'VegaliteViolin_PlotProperties',
    'VegaliteWaterfall_ChartProperties',
]
