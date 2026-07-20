# -*- coding: utf-8 -*-
"""
美线促销监控 - Flask 后端 (Parquet版)
"""
import os, json, gc, io
import pandas as pd
import numpy as np
from flask import Flask, jsonify, request, render_template, send_file
from datetime import datetime

app = Flask(__name__)

# 自动适配路径（Windows 本地 / Render Linux 通用）
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PARQUET_PATH = os.path.join(BASE_DIR, 'data.parquet')
FILTER_OPTS_PATH = os.path.join(BASE_DIR, 'filter_opts.json')

df = None
FILTER_RANGES = {}

def load_data():
    global df, FILTER_RANGES
    t0 = datetime.now()
    print(f"[{t0}] 加载 parquet...")
    df = pd.read_parquet(PARQUET_PATH)
    t1 = datetime.now()
    print(f"[{t1}] 加载完成: {len(df)} 行, {len(df.columns)} 列, 耗时 {(t1-t0).seconds}s")

    if os.path.exists(FILTER_OPTS_PATH):
        with open(FILTER_OPTS_PATH, 'r', encoding='utf-8') as f:
            FILTER_RANGES = json.load(f)

    # 确保周排序
    if '周' in df.columns:
        FILTER_RANGES['周'] = sorted(df['周'].dropna().unique().tolist())
    if '月' in df.columns:
        FILTER_RANGES['月'] = sorted(df['月'].dropna().unique().tolist())

    print(f"[{datetime.now()}] 业务组: {len(FILTER_RANGES.get('业务组',[]))} 个, 分类: {len(FILTER_RANGES.get('三级分类',[]))} 个")
    return df

def get_filtered_data(args):
    """Apply filters and return filtered dataframe"""
    global df
    d = df.copy()

    # 业务组
    vals = args.getlist('业务组')
    if vals and '业务组' in d.columns:
        d = d[d['业务组'].isin(vals)]

    # 三级分类
    vals = args.getlist('三级分类')
    if vals and '三级分类' in d.columns:
        d = d[d['三级分类'].isin(vals)]

    # BU
    vals = args.getlist('BU')
    if vals and 'BU' in d.columns:
        d = d[d['BU'].isin(vals)]

    # 最早SKU
    vals = args.getlist('最早SKU')
    if vals and '最早SKU' in d.columns:
        d = d[d['最早SKU'].isin(vals)]

    # Listing标识
    vals = args.getlist('Listing标识') or args.getlist('listing标识')
    if vals and 'Listing标识' in d.columns:
        d = d[d['Listing标识'].isin(vals)]

    # 月
    vals = args.getlist('月')
    if vals and '月' in d.columns:
        d = d[d['月'].isin(vals)]

    # 周
    vals = args.getlist('周')
    if vals and '周' in d.columns:
        d = d[d['周'].isin(vals)]

    # 按天
    vals = args.getlist('按天')
    if vals and '按天_str' in d.columns:
        d = d[d['按天_str'].isin(vals)]

    return d

# ========== API Routes ==========

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/filters')
def api_filters():
    return jsonify(FILTER_RANGES)

@app.route('/api/data_summary')
def api_data_summary():
    d = get_filtered_data(request.args)
    return jsonify({
        'total_rows': len(d),
        'distinct_sku': int(d['最早SKU'].nunique()),
        'distinct_listing': int(d['Listing标识'].nunique()),
        'total_spend': round(float(d['SPEND$'].sum()), 2),
        'total_sales': round(float(d['已订购商品销售额'].sum()), 2),
        'total_orders': round(float(d['已订购商品数量'].sum()), 2),
        'date_range': [
            str(d['按天_str'].min()) if not d.empty else '',
            str(d['按天_str'].max()) if not d.empty else ''
        ]
    })

@app.route('/api/chart1')
def api_chart1():
    """大组合图1: 周 - 已订购商品数量(柱) + SPEND$(线)"""
    d = get_filtered_data(request.args)
    agg = d.groupby('周').agg({'已订购商品数量': 'sum', 'SPEND$': 'sum'}).reset_index().sort_values('周')
    return jsonify({
        'labels': agg['周'].tolist(),
        '已订购商品数量': [float(x) for x in agg['已订购商品数量']],
        'SPEND$': [float(x) for x in agg['SPEND$']]
    })

@app.route('/api/chart2')
def api_chart2():
    """大组合图2: 周 - 促销%(柱) + 营销%(线)"""
    d = get_filtered_data(request.args)
    agg = d.groupby('周').agg({'促销费': 'sum', 'SPEND$': 'sum', '已订购商品销售额': 'sum'}).reset_index().sort_values('周')
    agg['促销%'] = np.where(agg['已订购商品销售额'] != 0, agg['促销费'] / agg['已订购商品销售额'] * 100, 0)
    agg['营销%'] = np.where(agg['已订购商品销售额'] != 0, agg['SPEND$'] / agg['已订购商品销售额'] * 100, 0)
    return jsonify({
        'labels': agg['周'].tolist(),
        '促销%': [round(float(x),2) for x in agg['促销%']],
        '营销%': [round(float(x),2) for x in agg['营销%']]
    })

@app.route('/api/chart3_bijia')
def api_chart3_bijia():
    """比价曲线"""
    d = get_filtered_data(request.args)
    pivot = d.groupby(['周', '比价类型'])['最早SKU'].nunique().reset_index()
    pivot.columns = ['周', '比价类型', 'SKU计数']
    labels = sorted(d['周'].dropna().unique())
    types = sorted(d['比价类型'].dropna().unique())
    result = {'labels': labels}
    for t in types:
        vd = dict(zip(pivot[pivot['比价类型']==t]['周'], pivot[pivot['比价类型']==t]['SKU计数']))
        result[t] = [int(vd.get(w,0)) for w in labels]
    return jsonify(result)

@app.route('/api/chart4_activity')
def api_chart4_activity():
    """活动曲线"""
    d = get_filtered_data(request.args)
    pivot = d.groupby(['周', '活动标识'])['最早SKU'].nunique().reset_index()
    pivot.columns = ['周', '活动标识', 'SKU计数']
    labels = sorted(d['周'].dropna().unique())
    desired = ['无活动', 'BD', '划线', 'Coupon', 'VM BD', '广告或DF解抑']
    types = [t for t in desired if t in d['活动标识'].unique()]
    result = {'labels': labels}
    for t in types:
        vd = dict(zip(pivot[pivot['活动标识']==t]['周'], pivot[pivot['活动标识']==t]['SKU计数']))
        result[t] = [int(vd.get(w,0)) for w in labels]
    return jsonify(result)

@app.route('/api/table1_big')
def api_table1_big():
    """大数汇总表格"""
    d = get_filtered_data(request.args)
    if d.empty:
        return jsonify([])

    grp = d.groupby(['月', '业务组', '三级分类'], sort=False)

    def agg_group(g):
        spend = float(g['SPEND$'].sum())
        sales = float(g['Total ads Sales$'].sum())
        orders = float(g['Total ads Units'].sum())
        impressions = float(g['IMPRESSIONS'].sum())
        clicks = float(g['CLICKS'].sum())
        page_views = float(g['页面浏览次数'].sum())
        qty = float(g['已订购商品数量'].sum())
        revenue = float(g['已订购商品销售额'].sum())
        promo_fee = float(g['促销费'].sum())
        rrp_total = float((g['RRP'] * g['已订购商品数量']).sum())
        actual_total = float((g['实际成交价'] * g['已订购商品数量']).sum())
        funding_total = float(g['funding_num'].sum())
        adv_sales = float(g['Advertised SKU Sales$'].sum())
        total_ads_orders = float(g['Total ads Orders'].sum())

        return {
            '最早SKU去重计数': int(g['最早SKU'].nunique()),
            'Listing标识去重计数': int(g['Listing标识'].nunique()),
            'SPEND$': round(spend,2),
            'Total ads Sales$': round(sales,2),
            'Total ads Units': int(orders),
            'IMPRESSIONS': int(impressions),
            'CLICKS': int(clicks),
            '页面浏览次数': round(page_views,2),
            '已订购商品数量': round(qty,2),
            '已订购商品销售额': round(revenue,2),
            '促销%': round(promo_fee/revenue*100 if revenue else 0, 2),
            '营销%': round(spend/revenue*100 if revenue else 0, 2),
            '折扣%': round((1 - actual_total/rrp_total)*100 if rrp_total else 0, 2),
            'funding%': round(funding_total/g['RRP'].sum()*100 if g['RRP'].sum() else 0, 2),
            'CTR%': round(clicks/impressions*100 if impressions else 0, 2),
            'T-CVR%': round(orders/clicks*100 if clicks else 0, 2),
            'T-CR%': round(qty/page_views*100 if page_views else 0, 2),
            '$CPC': round(spend/clicks if clicks else 0, 2),
            'ACOS%': round(spend/sales*100 if sales else 0, 2),
            'ROAS': round(sales/spend if spend else 0, 2),
            '$CPO': round(spend/total_ads_orders if total_ads_orders else 0, 2),
            '广告直购销额%': round(adv_sales/sales*100 if sales else 0, 2),
        }

    records = []
    prev = None
    for key, g in grp:
        month, biz, cat = key
        row = {'月': month, '业务组': biz, '三级分类': cat}
        row.update(agg_group(g))

        # 环比
        if prev and prev['业务组'] == biz and prev['三级分类'] == cat:
            for m in ['SPEND$', '已订购商品数量', 'Total ads Units']:
                pv = prev.get(m, 0)
                cv = row.get(m, 0)
                row[f'{m}环比%'] = round((cv-pv)/pv*100 if pv else 0, 2)
            prev = row
        else:
            for m in ['SPEND$', '已订购商品数量', 'Total ads Units']:
                row[f'{m}环比%'] = 0
            prev = row

        records.append(row)

    return jsonify(records)

@app.route('/api/table2_discount')
def api_table2_discount():
    """折扣区间汇总"""
    d = get_filtered_data(request.args)
    if d.empty:
        return jsonify([])

    grp = d.groupby('折扣打标', sort=False)
    records = []
    for label, g in grp:
        spend = float(g['SPEND$'].sum())
        sales = float(g['Total ads Sales$'].sum())
        orders = float(g['Total ads Units'].sum())
        impressions = float(g['IMPRESSIONS'].sum())
        clicks = float(g['CLICKS'].sum())
        page_views = float(g['页面浏览次数'].sum())
        qty = float(g['已订购商品数量'].sum())
        revenue = float(g['已订购商品销售额'].sum())
        promo_fee = float(g['促销费'].sum())
        rrp_total = float((g['RRP'] * g['已订购商品数量']).sum())
        actual_total = float((g['实际成交价'] * g['已订购商品数量']).sum())
        funding_total = float(g['funding_num'].sum())
        total_ads_orders = float(g['Total ads Orders'].sum())
        adv_sales = float(g['Advertised SKU Sales$'].sum())

        records.append({
            '折扣打标': str(label),
            '最早SKU去重计数': int(g['最早SKU'].nunique()),
            'Listing标识去重计数': int(g['Listing标识'].nunique()),
            'SPEND$': round(spend,2),
            'Total ads Sales$': round(sales,2),
            'Total ads Units': int(orders),
            'IMPRESSIONS': int(impressions),
            'CLICKS': int(clicks),
            '页面浏览次数': round(page_views,2),
            '已订购商品数量': round(qty,2),
            '已订购商品销售额': round(revenue,2),
            '促销%': round(promo_fee/revenue*100 if revenue else 0, 2),
            '营销%': round(spend/revenue*100 if revenue else 0, 2),
            '折扣%': round((1 - actual_total/rrp_total)*100 if rrp_total else 0, 2),
            'funding%': round(funding_total/g['RRP'].sum()*100 if g['RRP'].sum() else 0, 2),
            'CTR%': round(clicks/impressions*100 if impressions else 0, 2),
            'T-CVR%': round(orders/clicks*100 if clicks else 0, 2),
            'T-CR%': round(qty/page_views*100 if page_views else 0, 2),
            '$CPC': round(spend/clicks if clicks else 0, 2),
            'ACOS%': round(spend/sales*100 if sales else 0, 2),
            'ROAS': round(sales/spend if spend else 0, 2),
            '$CPO': round(spend/total_ads_orders if total_ads_orders else 0, 2),
            '广告直购销额%': round(adv_sales/sales*100 if sales else 0, 2),
        })

    return jsonify(records)

@app.route('/api/table3_promotion')
def api_table3_promotion():
    """促销汇总表格"""
    d = get_filtered_data(request.args)
    if d.empty:
        return jsonify([])

    grp = d.groupby(['月', '业务组', '三级分类'], sort=False)
    records = []
    for (month, biz, cat), g in grp:
        records.append({
            '月': month, '业务组': biz, '三级分类': cat,
            '最早SKU去重计数': int(g['最早SKU'].nunique()),
            'Listing标识去重计数': int(g['Listing标识'].nunique()),
            '活动计数': int(g[g['是否活动']=='活动']['最早SKU'].nunique()) if '活动' in g['是否活动'].values else 0,
            '比低价计数': int(g[g['比价类型']=='比低价']['最早SKU'].nunique()) if '比低价' in g['比价类型'].values else 0,
            '比高价计数': int(g[g['比价类型']=='比高价']['最早SKU'].nunique()) if '比高价' in g['比价类型'].values else 0,
            'BD标识计数': int(g[g['活动标识']=='BD']['最早SKU'].nunique()) if 'BD' in g['活动标识'].values else 0,
            'VM BD标识计数': int(g[g['活动标识']=='VM BD']['最早SKU'].nunique()) if 'VM BD' in g['活动标识'].values else 0,
            '比例一致计数': int(g[g['比例对比']=='比例一致']['最早SKU'].nunique()) if '比例一致' in g['比例对比'].values else 0,
            'funding更高计数': int(g[g['比例对比']=='funding更高']['最早SKU'].nunique()) if 'funding更高' in g['比例对比'].values else 0,
            'funding更低计数': int(g[g['比例对比']=='funding更低']['最早SKU'].nunique()) if 'funding更低' in g['比例对比'].values else 0,
        })

    return jsonify(records)

@app.route('/api/table4_listing')
def api_table4_listing():
    """上架汇总表格"""
    return api_table3_promotion()  # Same structure

@app.route('/api/trend1_category')
def api_trend1_category():
    """三级分类 funding% 趋势"""
    d = get_filtered_data(request.args)
    cats = request.args.getlist('三级分类') or d['三级分类'].unique().tolist()[:10]
    weeks = sorted(d['周'].dropna().unique())
    result = {'labels': weeks}
    for cat in cats:
        cd = d[d['三级分类']==cat]
        if cd.empty: continue
        grp = cd.groupby('周').apply(
            lambda g: float(g['funding_num'].sum() / g['RRP'].sum() * 100)
            if g['RRP'].sum() else 0
        ).reset_index()
        grp.columns = ['周', 'val']
        vd = dict(zip(grp['周'], grp['val']))
        result[cat] = [round(float(vd.get(w,0)),2) for w in weeks]
    return jsonify(result)

@app.route('/api/trend2_sku')
def api_trend2_sku():
    """SKU funding% 趋势"""
    d = get_filtered_data(request.args)
    skus = request.args.getlist('最早SKU') or d['最早SKU'].unique().tolist()[:10]
    weeks = sorted(d['周'].dropna().unique())
    result = {'labels': weeks}
    for sku in skus:
        sd = d[d['最早SKU']==sku]
        if sd.empty: continue
        grp = sd.groupby('周').apply(
            lambda g: float(g['funding_num'].sum() / g['RRP'].sum() * 100)
            if g['RRP'].sum() else 0
        ).reset_index()
        grp.columns = ['周', 'val']
        vd = dict(zip(grp['周'], grp['val']))
        result[sku] = [round(float(vd.get(w,0)),2) for w in weeks]
    return jsonify(result)

@app.route('/api/trend3_discount')
def api_trend3_discount():
    """折扣区间趋势"""
    d = get_filtered_data(request.args)
    pivot = d.groupby(['周', '折扣打标'])['最早SKU'].nunique().reset_index()
    pivot.columns = ['周', '折扣打标', 'SKU计数']
    labels = sorted(d['周'].dropna().unique())
    types = sorted([str(x) for x in d['折扣打标'].dropna().unique()])
    result = {'labels': labels}
    for t in types:
        vd = dict(zip(pivot[pivot['折扣打标'].astype(str)==t]['周'], pivot[pivot['折扣打标'].astype(str)==t]['SKU计数']))
        result[t] = [int(vd.get(w,0)) for w in labels]
    return jsonify(result)

@app.route('/api/detail_sku')
def api_detail_sku():
    """SKU-天明细"""
    d = get_filtered_data(request.args)
    skus = request.args.getlist('最早SKU')
    if skus:
        d = d[d['最早SKU'].isin(skus)]

    time_col = request.args.get('time_col', '按天_str')
    if time_col not in d.columns:
        time_col = '按天_str'

    grp = d.groupby(time_col, sort=False)

    records = []
    for t, g in grp:
        spend = float(g['SPEND$'].sum())
        sales = float(g['Total ads Sales$'].sum())
        orders = float(g['Total ads Orders'].sum())
        units = float(g['Total ads Units'].sum())
        impressions = float(g['IMPRESSIONS'].sum())
        clicks = float(g['CLICKS'].sum())
        page_views = float(g['页面浏览次数'].sum())
        qty = float(g['已订购商品数量'].sum())
        revenue = float(g['已订购商品销售额'].sum())
        promo_fee = float(g['促销费'].sum())
        rrp_total = float((g['RRP'] * g['已订购商品数量']).sum())
        actual_total = float((g['实际成交价'] * g['已订购商品数量']).sum())
        funding_total = float(g['funding_num'].sum())
        adv_sales = float(g['Advertised SKU Sales$'].sum())

        records.append({
            '按天': str(t),
            'Listing标识': str(g['Listing标识'].iloc[0]) if 'Listing标识' in g else '',
            '最早SKU': str(g['最早SKU'].iloc[0]) if '最早SKU' in g else '',
            '是否活动': str(g['是否活动'].iloc[0]) if '是否活动' in g else '',
            '比价类型': str(g['比价类型'].iloc[0]) if '比价类型' in g else '',
            '活动标识': str(g['活动标识'].iloc[0]) if '活动标识' in g else '',
            'SPEND$': round(spend,2),
            'Total ads Sales$': round(sales,2),
            'Total ads Units': int(units),
            'IMPRESSIONS': int(impressions),
            'CLICKS': int(clicks),
            '页面浏览次数': round(page_views,2),
            '已订购商品数量': round(qty,2),
            '已订购商品销售额': round(revenue,2),
            '促销%': round(promo_fee/revenue*100 if revenue else 0, 2),
            '营销%': round(spend/revenue*100 if revenue else 0, 2),
            '折扣%': round((1 - actual_total/rrp_total)*100 if rrp_total else 0, 2),
            'funding%': round(funding_total/g['RRP'].sum()*100 if g['RRP'].sum() else 0, 2),
            'CTR%': round(clicks/impressions*100 if impressions else 0, 2),
            'T-CVR%': round(units/clicks*100 if clicks else 0, 2),
            'T-CR%': round(qty/page_views*100 if page_views else 0, 2),
            '$CPC': round(spend/clicks if clicks else 0, 2),
            'ACOS%': round(spend/sales*100 if sales else 0, 2),
            'ROAS': round(sales/spend if spend else 0, 2),
            '$CPO': round(spend/orders if orders else 0, 2),
            '广告直购销额%': round(adv_sales/sales*100 if sales else 0, 2) if adv_sales else round(0, 2),
            'SPEND$环比%': 0, '已订购商品数量环比%': 0, 'Total ads Units环比%': 0,
        })

    return jsonify(records)

@app.route('/api/detail_listing')
def api_detail_listing():
    """Listing-天明细"""
    d = get_filtered_data(request.args)
    listings = request.args.getlist('Listing标识')
    if listings:
        d = d[d['Listing标识'].isin(listings)]

    time_col = request.args.get('time_col', '按天_str')
    if time_col not in d.columns:
        time_col = '按天_str'

    grp = d.groupby(time_col, sort=False)

    records = []
    for t, g in grp:
        spend = float(g['SPEND$'].sum())
        sales = float(g['Total ads Sales$'].sum())
        orders = float(g['Total ads Orders'].sum())
        units = float(g['Total ads Units'].sum())
        impressions = float(g['IMPRESSIONS'].sum())
        clicks = float(g['CLICKS'].sum())
        page_views = float(g['页面浏览次数'].sum())
        qty = float(g['已订购商品数量'].sum())
        revenue = float(g['已订购商品销售额'].sum())
        promo_fee = float(g['促销费'].sum())
        adv_sales = float(g['Advertised SKU Sales$'].sum())

        records.append({
            '按天': str(t),
            '最早SKU去重计数': int(g['最早SKU'].nunique()),
            'SPEND$': round(spend,2),
            'Total ads Sales$': round(sales,2),
            'Total ads Units': int(units),
            'IMPRESSIONS': int(impressions),
            'CLICKS': int(clicks),
            '页面浏览次数': round(page_views,2),
            '已订购商品数量': round(qty,2),
            '已订购商品销售额': round(revenue,2),
            '促销%': round(promo_fee/revenue*100 if revenue else 0, 2),
            '营销%': round(spend/revenue*100 if revenue else 0, 2),
            'CTR%': round(clicks/impressions*100 if impressions else 0, 2),
            'T-CVR%': round(units/clicks*100 if clicks else 0, 2),
            'T-CR%': round(qty/page_views*100 if page_views else 0, 2),
            '$CPC': round(spend/clicks if clicks else 0, 2),
            'ACOS%': round(spend/sales*100 if sales else 0, 2),
            'ROAS': round(sales/spend if spend else 0, 2),
            '$CPO': round(spend/orders if orders else 0, 2),
            '广告直购销额%': round(adv_sales/sales*100 if sales else 0, 2),
        })

    return jsonify(records)


@app.route('/api/export')
def api_export():
    """导出所有看板为 xlsx"""
    d = get_filtered_data(request.args)

    output = io.BytesIO()

    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        # Sheet1: 大数汇总
        grp = d.groupby(['月', '业务组', '三级分类'], sort=False)
        rows = []
        for (m, biz, cat), g in grp:
            spend = float(g['SPEND$'].sum())
            sales = float(g['Total ads Sales$'].sum())
            units = float(g['Total ads Units'].sum())
            impressions = float(g['IMPRESSIONS'].sum())
            clicks = float(g['CLICKS'].sum())
            pv = float(g['页面浏览次数'].sum())
            qty = float(g['已订购商品数量'].sum())
            revenue = float(g['已订购商品销售额'].sum())
            promo_fee = float(g['促销费'].sum())
            rrp_t = float((g['RRP'] * g['已订购商品数量']).sum())
            actual_t = float((g['实际成交价'] * g['已订购商品数量']).sum())
            funding_t = float(g['funding_num'].sum())
            adv_s = float(g['Advertised SKU Sales$'].sum())
            ads_orders = float(g['Total ads Orders'].sum())
            rows.append({
                '月': m, '业务组': biz, '三级分类': cat,
                '最早SKU去重计数': int(g['最早SKU'].nunique()),
                'Listing标识去重计数': int(g['Listing标识'].nunique()),
                'SPEND$': round(spend,2), 'Total ads Sales$': round(sales,2),
                'Total ads Units': int(units), 'IMPRESSIONS': int(impressions),
                'CLICKS': int(clicks), '页面浏览次数': round(pv,2),
                '已订购商品数量': round(qty,2), '已订购商品销售额': round(revenue,2),
                '促销%': round(promo_fee/revenue*100, 2) if revenue else 0,
                '营销%': round(spend/revenue*100, 2) if revenue else 0,
                '折扣%': round((1-actual_t/rrp_t)*100, 2) if rrp_t else 0,
                'funding%': round(funding_t/g['RRP'].sum()*100, 2) if g['RRP'].sum() else 0,
                'CTR%': round(clicks/impressions*100, 2) if impressions else 0,
                'T-CVR%': round(units/clicks*100, 2) if clicks else 0,
                'T-CR%': round(qty/pv*100, 2) if pv else 0,
                '$CPC': round(spend/clicks, 2) if clicks else 0,
                'ACOS%': round(spend/sales*100, 2) if sales else 0,
                'ROAS': round(sales/spend, 2) if spend else 0,
                '$CPO': round(spend/ads_orders, 2) if ads_orders else 0,
                '广告直购销额%': round(adv_s/sales*100, 2) if sales else 0,
            })
        if rows:
            pd.DataFrame(rows).to_excel(writer, sheet_name='大数汇总', index=False)

        # Sheet2: 折扣区间
        grp2 = d.groupby('折扣打标', sort=False)
        rows2 = []
        for label, g in grp2:
            spend = float(g['SPEND$'].sum())
            sales = float(g['Total ads Sales$'].sum())
            units = float(g['Total ads Units'].sum())
            impressions = float(g['IMPRESSIONS'].sum())
            clicks = float(g['CLICKS'].sum())
            pv = float(g['页面浏览次数'].sum())
            qty = float(g['已订购商品数量'].sum())
            revenue = float(g['已订购商品销售额'].sum())
            promo_fee = float(g['促销费'].sum())
            rrp_t = float((g['RRP'] * g['已订购商品数量']).sum())
            actual_t = float((g['实际成交价'] * g['已订购商品数量']).sum())
            funding_t = float(g['funding_num'].sum())
            adv_s = float(g['Advertised SKU Sales$'].sum())
            ads_orders = float(g['Total ads Orders'].sum())
            rows2.append({
                '折扣打标': str(label),
                '最早SKU去重计数': int(g['最早SKU'].nunique()),
                'Listing标识去重计数': int(g['Listing标识'].nunique()),
                'SPEND$': round(spend,2), 'Total ads Sales$': round(sales,2),
                'Total ads Units': int(units), 'IMPRESSIONS': int(impressions),
                'CLICKS': int(clicks), '页面浏览次数': round(pv,2),
                '已订购商品数量': round(qty,2), '已订购商品销售额': round(revenue,2),
                '促销%': round(promo_fee/revenue*100, 2) if revenue else 0,
                '营销%': round(spend/revenue*100, 2) if revenue else 0,
                '折扣%': round((1-actual_t/rrp_t)*100, 2) if rrp_t else 0,
                'funding%': round(funding_t/g['RRP'].sum()*100, 2) if g['RRP'].sum() else 0,
                'CTR%': round(clicks/impressions*100, 2) if impressions else 0,
                'T-CVR%': round(units/clicks*100, 2) if clicks else 0,
                'T-CR%': round(qty/pv*100, 2) if pv else 0,
                '$CPC': round(spend/clicks, 2) if clicks else 0,
                'ACOS%': round(spend/sales*100, 2) if sales else 0,
                'ROAS': round(sales/spend, 2) if spend else 0,
                '$CPO': round(spend/ads_orders, 2) if ads_orders else 0,
                '广告直购销额%': round(adv_s/sales*100, 2) if sales else 0,
            })
        if rows2:
            pd.DataFrame(rows2).to_excel(writer, sheet_name='折扣区间', index=False)

        # Sheet3: SKU明细（含全部计算字段）
        sku_detail = d.groupby(['按天_str', 'Listing标识', '最早SKU', '是否活动', '比价类型', '活动标识'], sort=False).agg({
            'SPEND$': 'sum', 'Total ads Sales$': 'sum', 'Total ads Units': 'sum',
            'IMPRESSIONS': 'sum', 'CLICKS': 'sum', '页面浏览次数': 'sum',
            '已订购商品数量': 'sum', '已订购商品销售额': 'sum', '促销费': 'sum',
            'RRP': 'first', '实际成交价': 'first', 'funding_num': 'sum',
            'Advertised SKU Sales$': 'sum', 'Total ads Orders': 'sum'
        }).reset_index()
        sku_detail['促销%'] = (sku_detail['促销费'] / sku_detail['已订购商品销售额'] * 100).round(2)
        sku_detail['营销%'] = (sku_detail['SPEND$'] / sku_detail['已订购商品销售额'] * 100).round(2)
        sku_detail['折扣%'] = ((1 - sku_detail['实际成交价'] / sku_detail['RRP']) * 100).round(2)
        sku_detail['funding%'] = (sku_detail['funding_num'] / sku_detail['RRP'] * 100).round(2)
        sku_detail['CTR%'] = (sku_detail['CLICKS'] / sku_detail['IMPRESSIONS'] * 100).round(2)
        sku_detail['T-CVR%'] = (sku_detail['Total ads Units'] / sku_detail['CLICKS'] * 100).round(2)
        sku_detail['T-CR%'] = (sku_detail['已订购商品数量'] / sku_detail['页面浏览次数'] * 100).round(2)
        sku_detail['$CPC'] = (sku_detail['SPEND$'] / sku_detail['CLICKS']).round(2)
        sku_detail['ACOS%'] = (sku_detail['SPEND$'] / sku_detail['Total ads Sales$'] * 100).round(2)
        sku_detail['ROAS'] = (sku_detail['Total ads Sales$'] / sku_detail['SPEND$']).round(2)
        sku_detail['$CPO'] = (sku_detail['SPEND$'] / sku_detail['Total ads Orders']).round(2)
        sku_detail['广告直购销额%'] = (sku_detail['Advertised SKU Sales$'] / sku_detail['Total ads Sales$'] * 100).round(2)
        sku_detail = sku_detail.rename(columns={
            '按天_str': '按天', 'Listing标识': 'Listing', 'funding_num': 'funding',
            '已订购商品数量': '已订购数量', '已订购商品销售额': '已订购销额',
            'Advertised SKU Sales$': '归因广告销额', 'Total ads Orders': '广告订单'
        })
        out_cols = ['按天','Listing','最早SKU','是否活动','比价类型','活动标识',
                    'SPEND$','Total ads Sales$','Total ads Units','IMPRESSIONS','CLICKS',
                    '页面浏览次数','已订购数量','已订购销额',
                    '促销%','营销%','折扣%','funding%','CTR%','T-CVR%','T-CR%',
                    '$CPC','ACOS%','ROAS','$CPO','广告直购销额%']
        sku_detail = sku_detail[[c for c in out_cols if c in sku_detail.columns]]
        if not sku_detail.empty:
            sku_detail.to_excel(writer, sheet_name='SKU明细', index=False)

        # Sheet4: 促销汇总
        prom_grp = d.groupby(['月', '业务组', '三级分类'], sort=False)
        prom_rows = []
        for (m, biz, cat), g in prom_grp:
            prom_rows.append({
                '月': m, '业务组': biz, '三级分类': cat,
                '最早SKU去重计数': int(g['最早SKU'].nunique()),
                'Listing标识去重计数': int(g['Listing标识'].nunique()),
                '活动计数': int(g[g['是否活动']=='活动']['最早SKU'].nunique()) if '活动' in g['是否活动'].values else 0,
                '比低价计数': int(g[g['比价类型']=='比低价']['最早SKU'].nunique()) if '比低价' in g['比价类型'].values else 0,
                '比高价计数': int(g[g['比价类型']=='比高价']['最早SKU'].nunique()) if '比高价' in g['比价类型'].values else 0,
                'BD标识计数': int(g[g['活动标识']=='BD']['最早SKU'].nunique()) if 'BD' in g['活动标识'].values else 0,
                'VM BD标识计数': int(g[g['活动标识']=='VM BD']['最早SKU'].nunique()) if 'VM BD' in g['活动标识'].values else 0,
                '比例一致计数': int(g[g['比例对比']=='比例一致']['最早SKU'].nunique()) if '比例一致' in g['比例对比'].values else 0,
                'funding更高计数': int(g[g['比例对比']=='funding更高']['最早SKU'].nunique()) if 'funding更高' in g['比例对比'].values else 0,
                'funding更低计数': int(g[g['比例对比']=='funding更低']['最早SKU'].nunique()) if 'funding更低' in g['比例对比'].values else 0,
            })
        if prom_rows:
            pd.DataFrame(prom_rows).to_excel(writer, sheet_name='促销汇总', index=False)

    output.seek(0)
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'美线促销监控_{datetime.now().strftime("%Y%m%d_%H%M")}.xlsx'
    )


def create_app():
    """Factory for Waitress / WSGI servers"""
    load_data()
    return app

if __name__ == '__main__':
    from waitress import serve
    print("="*60)
    print(" 美线促销监控看板 - 启动中...")
    print("="*60)
    load_data()
    print(f"[{datetime.now()}] ✅ 服务启动! http://127.0.0.1:5000")
    print(f"[{datetime.now()}] ⚡ 生产级 Waitress 服务器运行中")
    print("="*60)
    serve(app, host='0.0.0.0', port=5000, threads=8)
