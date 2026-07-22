# -*- coding: utf-8 -*-
"""
美线促销监控 - Flask 后端 (DuckDB版，低内存)
"""
import os, json, io
import duckdb
import pandas as pd
import numpy as np
from flask import Flask, jsonify, request, render_template, send_file
from datetime import datetime

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PARQUET_PATH = os.path.join(BASE_DIR, 'data.parquet')
JSON_PATH = os.path.join(BASE_DIR, 'filter_opts.json')

def get_filters():
    """从 JSON 加载筛选选项"""
    if os.path.exists(JSON_PATH):
        with open(JSON_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    # fallback: 从 parquet 查询
    conn = duckdb.connect()
    filters = {}
    for col in ['业务组','三级分类','BU','月','周','比价类型','是否活动','活动标识','折扣打标','比例对比']:
        rows = conn.execute(f"SELECT DISTINCT \"{col}\" FROM '{PARQUET_PATH}' WHERE \"{col}\" IS NOT NULL ORDER BY 1").fetchall()
        filters[col] = [r[0] for r in rows]
    conn.close()
    return filters

FILTER_RANGES = get_filters()

def query(sql, params=None):
    """执行 DuckDB 查询，返回 list[dict]"""
    conn = duckdb.connect()
    if params:
        result = conn.execute(sql, params).fetchdf()
    else:
        result = conn.execute(sql).fetchdf()
    conn.close()
    return result

def build_where(args):
    """从 request.args 构建 WHERE 条件"""
    clauses = []
    params = []
    for col in ['业务组','三级分类','BU','最早SKU','Listing标识']:
        vals = args.getlist(col)
        if vals:
            placeholders = ','.join(['?' for _ in vals])
            clauses.append(f'"{col}" IN ({placeholders})')
            params.extend(vals)
    for col in ['月','周']:
        vals = args.getlist(col)
        if vals:
            placeholders = ','.join(['?' for _ in vals])
            clauses.append(f'"{col}" IN ({placeholders})')
            params.extend(vals)
    vals = args.getlist('按天')
    if vals:
        placeholders = ','.join(['?' for _ in vals])
        clauses.append(f'"按天_str" IN ({placeholders})')
        params.extend(vals)
    where = ' AND '.join(clauses) if clauses else '1=1'
    return where, params

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/filters')
def api_filters():
    return jsonify(FILTER_RANGES)

@app.route('/api/data_summary')
def api_data_summary():
    w, p = build_where(request.args)
    sql = f"SELECT COUNT(*) as r, COUNT(DISTINCT \"最早SKU\") as sku, COUNT(DISTINCT \"Listing标识\") as listing, SUM(\"SPEND$\") as spend, SUM(\"已订购商品销售额\") as sales, SUM(\"已订购商品数量\") as qty, MIN(\"按天_str\") as dmin, MAX(\"按天_str\") as dmax FROM '{PARQUET_PATH}' WHERE {w}"
    df = query(sql, p)
    r = df.iloc[0]
    return jsonify({
        'total_rows': int(r['r']),
        'distinct_sku': int(r['sku']),
        'distinct_listing': int(r['listing']),
        'total_spend': round(float(r['spend'] or 0), 2),
        'total_sales': round(float(r['sales'] or 0), 2),
        'total_orders': round(float(r['qty'] or 0), 2),
        'date_range': [str(r['dmin'] or ''), str(r['dmax'] or '')]
    })

@app.route('/api/chart1')
def api_chart1():
    w, p = build_where(request.args)
    df = query(f"SELECT \"周\", SUM(\"已订购商品数量\") as qty, SUM(\"SPEND$\") as spend FROM '{PARQUET_PATH}' WHERE {w} GROUP BY \"周\" ORDER BY \"周\"", p)
    return jsonify({'labels': df['周'].tolist(), '已订购商品数量': [float(x) for x in df['qty']], 'SPEND$': [float(x) for x in df['spend']]})

@app.route('/api/chart2')
def api_chart2():
    w, p = build_where(request.args)
    df = query(f"SELECT \"周\", SUM(\"促销费\") as cf, SUM(\"SPEND$\") as spend, SUM(\"已订购商品销售额\") as sales FROM '{PARQUET_PATH}' WHERE {w} GROUP BY \"周\" ORDER BY \"周\"", p)
    df['促销%'] = np.where(df['sales'] != 0, df['cf'] / df['sales'] * 100, 0)
    df['营销%'] = np.where(df['sales'] != 0, df['spend'] / df['sales'] * 100, 0)
    return jsonify({'labels': df['周'].tolist(), '促销%': [round(float(x),2) for x in df['促销%']], '营销%': [round(float(x),2) for x in df['营销%']]})

@app.route('/api/chart3_bijia')
def api_chart3_bijia():
    w, p = build_where(request.args)
    df = query(f"SELECT \"周\", \"比价类型\", COUNT(DISTINCT \"最早SKU\") as cnt FROM '{PARQUET_PATH}' WHERE {w} AND \"比价类型\" IS NOT NULL GROUP BY \"周\", \"比价类型\" ORDER BY \"周\"", p)
    labels = sorted(df['周'].unique().tolist())
    types = sorted(df['比价类型'].unique().tolist())
    result = {'labels': labels}
    for t in types:
        sub = df[df['比价类型']==t]
        vd = dict(zip(sub['周'], sub['cnt']))
        result[t] = [int(vd.get(w,0)) for w in labels]
    return jsonify(result)

@app.route('/api/chart4_activity')
def api_chart4_activity():
    w, p = build_where(request.args)
    df = query(f"SELECT \"周\", \"活动标识\", COUNT(DISTINCT \"最早SKU\") as cnt FROM '{PARQUET_PATH}' WHERE {w} AND \"活动标识\" IS NOT NULL GROUP BY \"周\", \"活动标识\" ORDER BY \"周\"", p)
    labels = sorted(df['周'].unique().tolist())
    desired = ['无活动', 'BD', '划线', 'Coupon', 'VM BD', '广告或DF解抑']
    types = [t for t in desired if t in df['活动标识'].values]
    result = {'labels': labels}
    for t in types:
        sub = df[df['活动标识']==t]
        vd = dict(zip(sub['周'], sub['cnt']))
        result[t] = [int(vd.get(w,0)) for w in labels]
    return jsonify(result)

@app.route('/api/table1_big')
def api_table1_big():
    w, p = build_where(request.args)
    df = query(f"""
        SELECT \"月\",\"业务组\",\"三级分类\",
            COUNT(DISTINCT \"最早SKU\") as sku_cnt,
            COUNT(DISTINCT \"Listing标识\") as listing_cnt,
            SUM(\"SPEND$\") as spend,
            SUM(\"Total ads Sales$\") as ads_sales,
            SUM(\"Total ads Units\") as ads_units,
            SUM(\"IMPRESSIONS\") as imp,
            SUM(\"CLICKS\") as clicks,
            SUM(\"页面浏览次数\") as pv,
            SUM(\"已订购商品数量\") as qty,
            SUM(\"已订购商品销售额\") as revenue,
            SUM(\"促销费\") as promo_fee,
            SUM(\"RRP\" * \"已订购商品数量\") as rrp_total,
            SUM(\"实际成交价\" * \"已订购商品数量\") as actual_total,
            SUM(\"funding_num\") as funding_total,
            SUM(\"Advertised SKU Sales$\") as adv_sales,
            SUM(\"Total ads Orders\") as ads_orders
        FROM '{PARQUET_PATH}' WHERE {w}
        GROUP BY \"月\",\"业务组\",\"三级分类\"
        ORDER BY \"月\",\"业务组\",\"三级分类\"
    """, p)
    records = []
    prev = None
    for _, r in df.iterrows():
        row = {
            '月': r['月'], '业务组': r['业务组'], '三级分类': r['三级分类'],
            '最早SKU去重计数': int(r['sku_cnt']), 'Listing标识去重计数': int(r['listing_cnt']),
            'SPEND$': round(float(r['spend'] or 0),2),
            'Total ads Sales$': round(float(r['ads_sales'] or 0),2),
            'Total ads Units': int(r['ads_units'] or 0),
            'IMPRESSIONS': int(r['imp'] or 0), 'CLICKS': int(r['clicks'] or 0),
            '页面浏览次数': round(float(r['pv'] or 0),2),
            '已订购商品数量': round(float(r['qty'] or 0),2),
            '已订购商品销售额': round(float(r['revenue'] or 0),2),
            '促销%': round(float(r['promo_fee'] or 0)/(r['revenue'] or 1)*100,2),
            '营销%': round(float(r['spend'] or 0)/(r['revenue'] or 1)*100,2),
            '折扣%': round((1-(r['actual_total'] or 0)/(r['rrp_total'] or 1))*100,2),
            'funding%': round(float(r['funding_total'] or 0)/(r['rrp_total'] or 1)*100,2),
            'CTR%': round(float(r['clicks'] or 0)/(r['imp'] or 1)*100,2),
            'T-CVR%': round(float(r['ads_units'] or 0)/(r['clicks'] or 1)*100,2),
            'T-CR%': round(float(r['qty'] or 0)/(r['pv'] or 1)*100,2),
            '$CPC': round(float(r['spend'] or 0)/(r['clicks'] or 1),2),
            'ACOS%': round(float(r['spend'] or 0)/(r['ads_sales'] or 1)*100,2),
            'ROAS': round(float(r['ads_sales'] or 0)/(r['spend'] or 1),2),
            '$CPO': round(float(r['spend'] or 0)/(r['ads_orders'] or 1),2),
            '广告直购销额%': round(float(r['adv_sales'] or 0)/(r['ads_sales'] or 1)*100,2),
        }
        for m in ['SPEND$', '已订购商品数量', 'Total ads Units']:
            if prev and prev.get('月') and prev['业务组']==r['业务组'] and prev['三级分类']==r['三级分类']:
                cv = row[m]; pv = prev.get(m, 0)
                row[f'{m}环比%'] = round((cv-pv)/pv*100 if pv else 0, 2)
            else:
                row[f'{m}环比%'] = 0
        prev = row
        records.append(row)
    return jsonify(records)

@app.route('/api/table2_discount')
def api_table2_discount():
    w, p = build_where(request.args)
    df = query(f"""
        SELECT \"折扣打标\",
            COUNT(DISTINCT \"最早SKU\") as sku_cnt,
            COUNT(DISTINCT \"Listing标识\") as listing_cnt,
            SUM(\"SPEND$\") as spend,
            SUM(\"Total ads Sales$\") as ads_sales,
            SUM(\"Total ads Units\") as ads_units,
            SUM(\"IMPRESSIONS\") as imp,
            SUM(\"CLICKS\") as clicks,
            SUM(\"页面浏览次数\") as pv,
            SUM(\"已订购商品数量\") as qty,
            SUM(\"已订购商品销售额\") as revenue,
            SUM(\"促销费\") as promo_fee,
            SUM(\"RRP\" * \"已订购商品数量\") as rrp_total,
            SUM(\"实际成交价\" * \"已订购商品数量\") as actual_total,
            SUM(\"funding_num\") as funding_total,
            SUM(\"Advertised SKU Sales$\") as adv_sales,
            SUM(\"Total ads Orders\") as ads_orders
        FROM '{PARQUET_PATH}' WHERE {w} AND \"折扣打标\" IS NOT NULL
        GROUP BY \"折扣打标\"
    """, p)
    records = []
    for _, r in df.iterrows():
        records.append({
            '折扣打标': str(r['折扣打标']),
            '最早SKU去重计数': int(r['sku_cnt']), 'Listing标识去重计数': int(r['listing_cnt']),
            'SPEND$': round(float(r['spend'] or 0),2),
            'Total ads Sales$': round(float(r['ads_sales'] or 0),2),
            'Total ads Units': int(r['ads_units'] or 0),
            'IMPRESSIONS': int(r['imp'] or 0), 'CLICKS': int(r['clicks'] or 0),
            '页面浏览次数': round(float(r['pv'] or 0),2),
            '已订购商品数量': round(float(r['qty'] or 0),2),
            '已订购商品销售额': round(float(r['revenue'] or 0),2),
            '促销%': round(float(r['promo_fee'] or 0)/(r['revenue'] or 1)*100,2),
            '营销%': round(float(r['spend'] or 0)/(r['revenue'] or 1)*100,2),
            '折扣%': round((1-(r['actual_total'] or 0)/(r['rrp_total'] or 1))*100,2),
            'funding%': round(float(r['funding_total'] or 0)/(r['rrp_total'] or 1)*100,2),
            'CTR%': round(float(r['clicks'] or 0)/(r['imp'] or 1)*100,2),
            'T-CVR%': round(float(r['ads_units'] or 0)/(r['clicks'] or 1)*100,2),
            'T-CR%': round(float(r['qty'] or 0)/(r['pv'] or 1)*100,2),
            '$CPC': round(float(r['spend'] or 0)/(r['clicks'] or 1),2),
            'ACOS%': round(float(r['spend'] or 0)/(r['ads_sales'] or 1)*100,2),
            'ROAS': round(float(r['ads_sales'] or 0)/(r['spend'] or 1),2),
            '$CPO': round(float(r['spend'] or 0)/(r['ads_orders'] or 1),2),
            '广告直购销额%': round(float(r['adv_sales'] or 0)/(r['ads_sales'] or 1)*100,2),
        })
    return jsonify(records)

@app.route('/api/table3_promotion')
def api_table3_promotion():
    w, p = build_where(request.args)
    df = query(f"""
        SELECT \"月\",\"业务组\",\"三级分类\",
            COUNT(DISTINCT \"最早SKU\") as sku_cnt,
            COUNT(DISTINCT \"Listing标识\") as listing_cnt,
            COUNT(DISTINCT CASE WHEN \"是否活动\"='活动' THEN \"最早SKU\" END) as active_cnt,
            COUNT(DISTINCT CASE WHEN \"比价类型\"='比低价' THEN \"最早SKU\" END) as low_cnt,
            COUNT(DISTINCT CASE WHEN \"比价类型\"='比高价' THEN \"最早SKU\" END) as high_cnt,
            COUNT(DISTINCT CASE WHEN \"活动标识\"='BD' THEN \"最早SKU\" END) as bd_cnt,
            COUNT(DISTINCT CASE WHEN \"活动标识\"='VM BD' THEN \"最早SKU\" END) as vm_cnt,
            COUNT(DISTINCT CASE WHEN \"比例对比\"='比例一致' THEN \"最早SKU\" END) as same_cnt,
            COUNT(DISTINCT CASE WHEN \"比例对比\"='funding更高' THEN \"最早SKU\" END) as f_up_cnt,
            COUNT(DISTINCT CASE WHEN \"比例对比\"='funding更低' THEN \"最早SKU\" END) as f_down_cnt
        FROM '{PARQUET_PATH}' WHERE {w}
        GROUP BY \"月\",\"业务组\",\"三级分类\"
    """, p)
    records = []
    for _, r in df.iterrows():
        records.append({
            '月': r['月'], '业务组': r['业务组'], '三级分类': r['三级分类'],
            '最早SKU去重计数': int(r['sku_cnt']), 'Listing标识去重计数': int(r['listing_cnt']),
            '活动计数': int(r['active_cnt'] or 0),
            '比低价计数': int(r['low_cnt'] or 0), '比高价计数': int(r['high_cnt'] or 0),
            'BD标识计数': int(r['bd_cnt'] or 0), 'VM BD标识计数': int(r['vm_cnt'] or 0),
            '比例一致计数': int(r['same_cnt'] or 0),
            'funding更高计数': int(r['f_up_cnt'] or 0),
            'funding更低计数': int(r['f_down_cnt'] or 0),
        })
    return jsonify(records)

@app.route('/api/table4_listing')
def api_table4_listing():
    return api_table3_promotion()

@app.route('/api/trend1_category')
def api_trend1_category():
    w, p = build_where(request.args)
    df = query(f"""
        SELECT \"周\",\"三级分类\",
            SUM(\"funding_num\")/NULLIF(SUM(\"RRP\"),0)*100 as val
        FROM '{PARQUET_PATH}' WHERE {w}
        GROUP BY \"周\",\"三级分类\" ORDER BY \"周\"
    """, p)
    cats = request.args.getlist('三级分类') or df['三级分类'].unique().tolist()[:10]
    weeks = sorted(df['周'].unique().tolist())
    result = {'labels': weeks}
    for cat in cats:
        sub = df[df['三级分类']==cat]
        vd = dict(zip(sub['周'], sub['val']))
        result[cat] = [round(float(vd.get(w,0)),2) for w in weeks]
    return jsonify(result)

@app.route('/api/trend2_sku')
def api_trend2_sku():
    w, p = build_where(request.args)
    df = query(f"""
        SELECT \"周\",\"最早SKU\",
            SUM(\"funding_num\")/NULLIF(SUM(\"RRP\"),0)*100 as val
        FROM '{PARQUET_PATH}' WHERE {w}
        GROUP BY \"周\",\"最早SKU\" ORDER BY \"周\"
    """, p)
    skus = request.args.getlist('最早SKU') or df['最早SKU'].unique().tolist()[:10]
    weeks = sorted(df['周'].unique().tolist())
    result = {'labels': weeks}
    for sku in skus:
        sub = df[df['最早SKU']==sku]
        vd = dict(zip(sub['周'], sub['val']))
        result[sku] = [round(float(vd.get(w,0)),2) for w in weeks]
    return jsonify(result)

@app.route('/api/trend3_discount')
def api_trend3_discount():
    w, p = build_where(request.args)
    df = query(f"""
        SELECT \"周\",\"折扣打标\",
            COUNT(DISTINCT \"最早SKU\") as cnt
        FROM '{PARQUET_PATH}' WHERE {w} AND \"折扣打标\" IS NOT NULL
        GROUP BY \"周\",\"折扣打标\" ORDER BY \"周\"
    """, p)
    labels = sorted(df['周'].unique().tolist())
    types = sorted([str(x) for x in df['折扣打标'].unique()])
    result = {'labels': labels}
    for t in types:
        sub = df[df['折扣打标'].astype(str)==t]
        vd = dict(zip(sub['周'], sub['cnt']))
        result[t] = [int(vd.get(w,0)) for w in labels]
    return jsonify(result)

@app.route('/api/detail_sku')
def api_detail_sku():
    w, p = build_where(request.args)
    skus = request.args.getlist('最早SKU')
    if skus:
        ph = ','.join(['?' for _ in skus])
        if w == '1=1':
            w = f'"最早SKU" IN ({ph})'
        else:
            w = f'({w}) AND "最早SKU" IN ({ph})'
        p.extend(skus)
    df = query(f"""
        SELECT \"按天_str\",\"Listing标识\",\"最早SKU\",\"是否活动\",\"比价类型\",\"活动标识\",
            \"RRP\",\"实际成交价\",
            SUM(\"SPEND$\") as spend, SUM(\"Total ads Sales$\") as ads_sales,
            SUM(\"Total ads Units\") as ads_units, SUM(\"IMPRESSIONS\") as imp,
            SUM(\"CLICKS\") as clicks, SUM(\"页面浏览次数\") as pv,
            SUM(\"已订购商品数量\") as qty, SUM(\"已订购商品销售额\") as revenue,
            SUM(\"促销费\") as promo_fee, SUM(\"funding_num\") as funding,
            SUM(\"Advertised SKU Sales$\") as adv_sales, SUM(\"Total ads Orders\") as ads_orders
        FROM '{PARQUET_PATH}' WHERE {w}
        GROUP BY \"按天_str\",\"Listing标识\",\"最早SKU\",\"是否活动\",\"比价类型\",\"活动标识\",\"RRP\",\"实际成交价\"
        ORDER BY \"按天_str\"
    """, p)
    records = []
    for _, r in df.iterrows():
        spend = float(r['spend'] or 0)
        sales = float(r['ads_sales'] or 0)
        revenue = float(r['revenue'] or 0)
        clicks = float(r['clicks'] or 0)
        imp = float(r['imp'] or 0)
        pv = float(r['pv'] or 0)
        qty = float(r['qty'] or 0)
        rrp = float(r['RRP'] or 0)
        actual = float(r['实际成交价'] or 0)
        funding = float(r['funding'] or 0)
        records.append({
            '按天': str(r['按天_str']),
            'Listing标识': str(r['Listing标识'] or ''),
            '最早SKU': str(r['最早SKU'] or ''),
            '是否活动': str(r['是否活动'] or ''),
            '比价类型': str(r['比价类型'] or ''),
            '活动标识': str(r['活动标识'] or ''),
            'RRP': round(rrp,2), '实际成交价': round(actual,2),
            'funding': round(funding,2),
            'SPEND$': round(spend,2), 'Total ads Sales$': round(sales,2),
            'Total ads Units': int(r['ads_units'] or 0),
            'IMPRESSIONS': int(imp), 'CLICKS': int(clicks),
            '页面浏览次数': round(pv,2),
            '已订购商品数量': round(qty,2), '已订购商品销售额': round(revenue,2),
            '促销%': round((r['promo_fee'] or 0)/revenue*100 if revenue else 0,2),
            '营销%': round(spend/revenue*100 if revenue else 0,2),
            '折扣%': round((1-actual/rrp)*100 if rrp else 0,2),
            'funding%': round(funding/rrp*100 if rrp else 0,2),
            'CTR%': round(clicks/imp*100 if imp else 0,2),
            'T-CVR%': round(float(r['ads_units'] or 0)/clicks*100 if clicks else 0,2),
            'T-CR%': round(qty/pv*100 if pv else 0,2),
            '$CPC': round(spend/clicks if clicks else 0,2),
            'ACOS%': round(spend/sales*100 if sales else 0,2),
            'ROAS': round(sales/spend if spend else 0,2),
            '$CPO': round(spend/(r['ads_orders'] or 1) if (r['ads_orders'] or 0) else 0,2),
            '广告直购销额%': round(float(r['adv_sales'] or 0)/sales*100 if sales else 0,2),
            'SPEND$环比%': 0, '已订购商品数量环比%': 0, 'Total ads Units环比%': 0,
        })
    return jsonify(records)

@app.route('/api/detail_listing')
def api_detail_listing():
    w, p = build_where(request.args)
    listings = request.args.getlist('Listing标识')
    if listings:
        ph = ','.join(['?' for _ in listings])
        if w == '1=1':
            w = f'"Listing标识" IN ({ph})'
        else:
            w = f'({w}) AND "Listing标识" IN ({ph})'
        p.extend(listings)
    df = query(f"""
        SELECT \"按天_str\",
            COUNT(DISTINCT \"最早SKU\") as sku_cnt,
            SUM(\"SPEND$\") as spend, SUM(\"Total ads Sales$\") as ads_sales,
            SUM(\"Total ads Units\") as ads_units, SUM(\"IMPRESSIONS\") as imp,
            SUM(\"CLICKS\") as clicks, SUM(\"页面浏览次数\") as pv,
            SUM(\"已订购商品数量\") as qty, SUM(\"已订购商品销售额\") as revenue,
            SUM(\"促销费\") as promo_fee,
            SUM(\"Advertised SKU Sales$\") as adv_sales, SUM(\"Total ads Orders\") as ads_orders
        FROM '{PARQUET_PATH}' WHERE {w}
        GROUP BY \"按天_str\" ORDER BY \"按天_str\"
    """, p)
    records = []
    for _, r in df.iterrows():
        records.append({
            '按天': str(r['按天_str']),
            '最早SKU去重计数': int(r['sku_cnt']),
            'SPEND$': round(float(r['spend'] or 0),2),
            'Total ads Sales$': round(float(r['ads_sales'] or 0),2),
            'Total ads Units': int(r['ads_units'] or 0),
            'IMPRESSIONS': int(r['imp'] or 0), 'CLICKS': int(r['clicks'] or 0),
            '页面浏览次数': round(float(r['pv'] or 0),2),
            '已订购商品数量': round(float(r['qty'] or 0),2),
            '已订购商品销售额': round(float(r['revenue'] or 0),2),
            '促销%': round(float(r['promo_fee'] or 0)/(r['revenue'] or 1)*100,2),
            '营销%': round(float(r['spend'] or 0)/(r['revenue'] or 1)*100,2),
            'CTR%': round(float(r['clicks'] or 0)/(r['imp'] or 1)*100,2),
            'T-CVR%': round(float(r['ads_units'] or 0)/(r['clicks'] or 1)*100,2),
            'T-CR%': round(float(r['qty'] or 0)/(r['pv'] or 1)*100,2),
            '$CPC': round(float(r['spend'] or 0)/(r['clicks'] or 1),2),
            'ACOS%': round(float(r['spend'] or 0)/(r['ads_sales'] or 1)*100,2),
            'ROAS': round(float(r['ads_sales'] or 0)/(r['spend'] or 1),2),
            '$CPO': round(float(r['spend'] or 0)/(r['ads_orders'] or 1),2),
            '广告直购销额%': round(float(r['adv_sales'] or 0)/(r['ads_sales'] or 1)*100,2),
        })
    return jsonify(records)

@app.route('/api/export')
def api_export():
    w, p = build_where(request.args)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        # Sheet1
        df1 = query(f"""
            SELECT \"月\",\"业务组\",\"三级分类\",
                COUNT(DISTINCT \"最早SKU\") as sku_cnt,
                COUNT(DISTINCT \"Listing标识\") as listing_cnt,
                SUM(\"SPEND$\") as spend,
                SUM(\"Total ads Sales$\") as ads_sales,
                SUM(\"Total ads Units\") as ads_units,
                SUM(\"IMPRESSIONS\") as imp,
                SUM(\"CLICKS\") as clicks,
                SUM(\"页面浏览次数\") as pv,
                SUM(\"已订购商品数量\") as qty,
                SUM(\"已订购商品销售额\") as revenue,
                SUM(\"促销费\") as promo_fee,
                SUM(\"funding_num\") as funding_t,
                SUM(\"Advertised SKU Sales$\") as adv_sales_t,
                SUM(\"Total ads Orders\") as ads_orders_t
            FROM '{PARQUET_PATH}' WHERE {w}
            GROUP BY \"月\",\"业务组\",\"三级分类\"
        """, p)
        if not df1.empty:
            df1.to_excel(writer, sheet_name='大数汇总', index=False)

        # Sheet2
        df2 = query(f"""
            SELECT \"折扣打标\",
                COUNT(DISTINCT \"最早SKU\") as sku_cnt,
                COUNT(DISTINCT \"Listing标识\") as listing_cnt,
                SUM(\"SPEND$\") as spend,
                SUM(\"Total ads Sales$\") as ads_sales,
                SUM(\"Total ads Units\") as ads_units,
                SUM(\"IMPRESSIONS\") as imp,
                SUM(\"CLICKS\") as clicks,
                SUM(\"页面浏览次数\") as pv,
                SUM(\"已订购商品数量\") as qty,
                SUM(\"已订购商品销售额\") as revenue,
                SUM(\"促销费\") as promo_fee
            FROM '{PARQUET_PATH}' WHERE {w} AND \"折扣打标\" IS NOT NULL
            GROUP BY \"折扣打标\"
        """, p)
        if not df2.empty:
            df2.to_excel(writer, sheet_name='折扣区间', index=False)

    output.seek(0)
    return send_file(output, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                     as_attachment=True,
                     download_name=f'美线促销监控_{datetime.now().strftime("%Y%m%d_%H%M")}.xlsx')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print("美线促销监控看板 - 启动中...")
    app.run(host='0.0.0.0', port=port, debug=True)
