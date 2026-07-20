# -*- coding: utf-8 -*-
"""美线促销数据预处理 - Excel转Parquet"""
import pandas as pd
import numpy as np
import time, os, warnings
warnings.filterwarnings('ignore')

t0 = time.time()
CACHE_DIR = r'C:\Users\thinkpad\Desktop\促销数据\美线促销监控'
os.makedirs(CACHE_DIR, exist_ok=True)

print('开始读取Excel...')
df = pd.read_excel(
    r'C:\Users\thinkpad\Desktop\促销数据\美线按天促销数据.xlsx',
    sheet_name='Sheet1'
)
t1 = time.time()
print(f'读取完成: {len(df)} 行, {len(df.columns)} 列, 耗时 {t1-t0:.0f}s')

# 清洗：过滤掉"按天"列是文本"按天"的异常行
df = df[df['按天'] != '按天'].copy()
print(f'清洗后: {len(df)} 行')

# 删除混合类型列（周期列混合了int和str）
for col in ['周期', 'asin']:
    if col in df.columns:
        df = df.drop(columns=[col])
        print(f'删除混合类型列: {col}')

# 日期处理 - 格式如 2026-1-1（无前导零）
df['按天'] = pd.to_datetime(df['按天'], errors='coerce')
df = df.dropna(subset=['按天'])
df['按天_str'] = df['按天'].apply(lambda x: f'{x.year}-{x.month}-{x.day}')
# 月去前导零：2026-01 -> 2026-1
df['月'] = df['按天'].apply(lambda x: f'{x.year}-{x.month}')

# 数值填充
num_base = ['SPEND$','Total ads Sales$','Total ads Orders','Total ads Units',
            'Advertised SKU Sales$','IMPRESSIONS','CLICKS','页面浏览次数',
            '已订购商品数量','已订购商品销售额','RRP','实际成交价','理论成交价','促销费']
for c in num_base:
    if c in df.columns:
        df[c] = pd.to_numeric(df[c], errors='coerce').fillna(0)

# funding处理
df['funding_num'] = pd.to_numeric(df['funding'], errors='coerce').fillna(0)

print('计算衍生字段...')
# 促销%
df['促销%'] = np.where(df['已订购商品销售额'] != 0, df['促销费'] / df['已订购商品销售额'], 0)
# 营销%
df['营销%'] = np.where(df['已订购商品销售额'] != 0, df['SPEND$'] / df['已订购商品销售额'], 0)
# 折扣% = 1 - (实际成交价 / RRP)
df['折扣%'] = np.where(df['RRP'] != 0, 1 - (df['实际成交价'] / df['RRP']), 0)
# funding% = funding / RRP（百分比格式，如 12/56.99=21%）
df['funding%'] = np.where(df['RRP'] != 0, df['funding_num'] / df['RRP'] * 100, 0)
# CTR%
df['CTR%'] = np.where(df['IMPRESSIONS'] != 0, df['CLICKS'] / df['IMPRESSIONS'], 0)
# T-CVR%
df['T-CVR%'] = np.where(df['CLICKS'] != 0, df['Total ads Units'] / df['CLICKS'], 0)
# T-CR%
df['T-CR%'] = np.where(df['页面浏览次数'] != 0, df['已订购商品数量'] / df['页面浏览次数'], 0)
# $CPC
df['$CPC'] = np.where(df['CLICKS'] != 0, df['SPEND$'] / df['CLICKS'], 0)
# ACOS%
df['ACOS%'] = np.where(df['Total ads Sales$'] != 0, df['SPEND$'] / df['Total ads Sales$'], 0)
# ROAS
df['ROAS'] = np.where(df['SPEND$'] != 0, df['Total ads Sales$'] / df['SPEND$'], 0)
# $CPO
df['$CPO'] = np.where(df['Total ads Orders'] != 0, df['SPEND$'] / df['Total ads Orders'], 0)
# 广告直购销额%
df['广告直购销额%'] = np.where(df['Total ads Sales$'] != 0, df['Advertised SKU Sales$'] / df['Total ads Sales$'], 0)

# 填充空值
for c in ['页面浏览次数','已订购商品数量','已订购商品销售额','IMPRESSIONS','CLICKS',
          'SPEND$','Total ads Sales$','Total ads Units']:
    if c in df.columns:
        df[c] = df[c].fillna(0)

# 环比
print('计算环比...')
df = df.sort_values(['最早SKU', '按天'])
for metric in ['SPEND$', '已订购商品数量', 'Total ads Units']:
    col_name = metric + '环比%'
    df[col_name] = df.groupby('最早SKU')[metric].transform(lambda x: x.pct_change().fillna(0))

# 上架年月
if '上架年月' in df.columns:
    df['上架年月'] = df['上架年月'].astype(str)

# 确保所有object列都是字符串类型
for col in df.select_dtypes(include=['object']).columns:
    df[col] = df[col].astype(str)

# 确保所有数值列都是float64
for col in ['SPEND$','Total ads Sales$','Total ads Orders','Total ads Units','IMPRESSIONS','CLICKS',
            '已订购商品数量','已订购商品销售额','RRP','实际成交价','理论成交价','促销费','funding_num',
            '促销%','营销%','折扣%','funding%','CTR%','T-CVR%','T-CR%','$CPC','ACOS%','ROAS','$CPO','广告直购销额%',
            'Advertised SKU Sales$','页面浏览次数','SPEND$环比%','已订购商品数量环比%','Total ads Units环比%']:
    if col in df.columns:
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype('float64')

# 保存为 parquet
out = os.path.join(CACHE_DIR, 'data.parquet')
t2 = time.time()
df.to_parquet(out, index=False)
t3 = time.time()
size_mb = os.path.getsize(out) / 1024 / 1024

# 同时保存筛选选项 JSON
filter_opts = {}
for col in ['业务组','三级分类','BU','月','周','比价类型','是否活动','活动标识','折扣打标','比例对比']:
    if col in df.columns:
        vals = sorted(df[col].dropna().unique().tolist())
        filter_opts[col] = [str(v) for v in vals]

import json
with open(os.path.join(CACHE_DIR, 'filter_opts.json'), 'w', encoding='utf-8') as f:
    json.dump(filter_opts, f, ensure_ascii=False, indent=2)

t4 = time.time()
print(f'\n预处理完成!')
print(f'  最终行数: {len(df)}')
print(f'  Parquet文件: {size_mb:.1f} MB')
print(f'  总耗时: {t4-t0:.0f}s')
print(f'  字段数: {len(df.columns)}')
for c in sorted(filter_opts.keys()):
    print(f'  {c}: {len(filter_opts[c])} 个值')
