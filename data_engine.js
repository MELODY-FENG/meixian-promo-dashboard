/**
 * DataEngine - Client-side data processing for static dashboard
 * Ports all Python server API logic to JavaScript using TypedArrays
 */
class DataEngine {
  constructor() {
    this.meta = null; this.cat = {}; this.num = {}; this.nRows = 0; this.ready = false;
  }
  async init(metaUrl, dataUrl) {
    this.meta = await fetch(metaUrl).then(r => r.json());
    this.nRows = this.meta.n_rows;
    const response = await fetch(dataUrl);
    let buf;
    if (this.meta.compressed) {
      buf = await new Response(response.body.pipeThrough(new DecompressionStream('gzip'))).arrayBuffer();
    } else {
      buf = await response.arrayBuffer();
    }
    const hdr = new Uint32Array(buf, 0, 3);
    let off = 12;
    for (const c of this.meta.cat_cols) { this.cat[c] = new Uint16Array(buf, off, this.nRows); off += this.nRows * 2; }
    for (const c of this.meta.num_cols) { this.num[c] = new Float32Array(buf, off, this.nRows); off += this.nRows * 4; }
    this.ready = true;
  }
  sd(a,b){return b!==0?a/b:0;}
  hb(c,p){return p!==0?Math.round((c-p)/Math.abs(p)*1e4)/100:0;}
  applyFilters(p) {
    const m = new Uint8Array(this.nRows).fill(1);
    const fm = {sku:'sku',listing:'listing',biz_group:'biz_group',category:'category',bu:'bu',month:'month',week:'week',day:'day',discount_tag:'discount_tag',is_activity:'is_activity'};
    for (const [pk,ck] of Object.entries(fm)) {
      const v = p[pk]; if(!v||!this.cat[ck])continue;
      const sel = v.split(',').map(s=>s.trim()).filter(s=>s); if(!sel.length)continue;
      const lk = this.meta.lookups[ck]; const si = new Set();
      for (const s of sel) { const idx=lk.indexOf(s); if(idx>=0)si.add(idx); }
      if(!si.size)continue;
      const cd = this.cat[ck];
      for(let i=0;i<this.nRows;i++){if(m[i]&&!si.has(cd[i]))m[i]=0;}
    }
    return m;
  }
  sumNum(m) {
    const r={}; const cols=['SPEND$','Total ads Sales$','Total ads Orders','Total ads Units','Advertised SKU Sales$','IMPRESSIONS','CLICKS','页面浏览次数','已订购商品数量','已订购商品销售额','RRP','实际成交价','理论成交价','促销费','funding_num'];
    for(const c of cols){let s=0;const d=this.num[c];for(let i=0;i<this.nRows;i++)if(m[i])s+=d[i];r[c]=s;}
    return r;
  }
  metrics(s){return{'促销%':Math.round(this.sd(s['促销费'],s['已订购商品销售额'])*1e4)/100,'营销%':Math.round(this.sd(s['SPEND$'],s['已订购商品销售额'])*1e4)/100,'折扣%':Math.round((1-this.sd(s['实际成交价'],s['RRP']))*1e4)/100,'funding%':Math.round(this.sd(s['funding_num'],s['RRP'])*1e4)/100,'CTR%':Math.round(this.sd(s['CLICKS'],s['IMPRESSIONS'])*1e4)/100,'T-CVR%':Math.round(this.sd(s['Total ads Units'],s['CLICKS'])*1e4)/100,'T-CR%':Math.round(this.sd(s['已订购商品数量'],s['页面浏览次数'])*1e4)/100,'$CPC':Math.round(this.sd(s['SPEND$'],s['CLICKS'])*100)/100,'ACOS%':Math.round(this.sd(s['SPEND$'],s['Total ads Sales$'])*1e4)/100,'ROAS':Math.round(this.sd(s['Total ads Sales$'],s['SPEND$'])*100)/100,'$CPO':Math.round(this.sd(s['SPEND$'],s['Total ads Orders'])*100)/100,'广告直购销额%':Math.round(this.sd(s['Advertised SKU Sales$'],s['Total ads Sales$'])*1e4)/100};}
  getFilterOptions(p){
    const m=this.applyFilters(p);const o={};
    for(const k of['biz_group','category','bu','sku','listing','month','week','day']){
      if(!this.cat[k])continue;const lk=this.meta.lookups[k];const cd=this.cat[k];const seen=new Set();const vals=[];
      for(let i=0;i<this.nRows;i++){if(!m[i])continue;const v=lk[cd[i]];if(v&&v!=='nan'&&v!=='NaT'&&v!=='0'&&!seen.has(v)){seen.add(v);vals.push(v);}}
      vals.sort();o[k]=vals;
    }
    return o;
  }
  apiWeekly(m){
    const wi=this.cat['week'],weeks=this.meta.lookups['week'],nw=weeks.length;const r={weeks};
    const mks=['已订购商品数量','SPEND$','促销%','营销%','折扣%','funding%','CTR%','T-CVR%','T-CR%','$CPC','ACOS%','ROAS','$CPO','广告直购销额%'];
    for(const k of mks)r[k]=new Array(nw).fill(0);
    const sc=['SPEND$','Total ads Sales$','Total ads Orders','Total ads Units','Advertised SKU Sales$','IMPRESSIONS','CLICKS','页面浏览次数','已订购商品数量','已订购商品销售额','RRP','实际成交价','促销费','funding_num'];
    for(let w=0;w<nw;w++){
      const s={};for(const c of sc)s[c]=0;let has=false;
      for(let i=0;i<this.nRows;i++){if(m[i]&&wi[i]===w){has=true;for(const c of sc)s[c]+=this.num[c][i];}}
      if(has){r['已订购商品数量'][w]=Math.round(s['已订购商品数量']);r['SPEND$'][w]=Math.round(s['SPEND$']*100)/100;const mt=this.metrics(s);for(const k of['促销%','营销%','折扣%','funding%','CTR%','T-CVR%','T-CR%','$CPC','ACOS%','ROAS','$CPO','广告直购销额%'])r[k][w]=mt[k];}
    }
    return r;
  }
  apiPrice(m){
    const wi=this.cat['week'],pi=this.cat['price_type'],si=this.cat['sku'];const weeks=this.meta.lookups['week'];const pts=this.meta.lookups['price_type'];const result={};
    for(let p_i=0;p_i<pts.length;p_i++){const cd=new Array(weeks.length).fill(0);for(let w_i=0;w_i<weeks.length;w_i++){const seen=new Set();for(let i=0;i<this.nRows;i++){if(m[i]&&wi[i]===w_i&&pi[i]===p_i)seen.add(si[i]);}cd[w_i]=seen.size;}result[pts[p_i]]=cd;}
    return{weeks,price_types:pts,data:result};
  }
  apiActivity(m){
    const wi=this.cat['week'],ai=this.cat['activity'],si=this.cat['sku'];const weeks=this.meta.lookups['week'];const acts=this.meta.lookups['activity'];const result={};
    for(let a_i=0;a_i<acts.length;a_i++){const cd=new Array(weeks.length).fill(0);for(let w_i=0;w_i<weeks.length;w_i++){const seen=new Set();for(let i=0;i<this.nRows;i++){if(m[i]&&wi[i]===w_i&&ai[i]===a_i)seen.add(si[i]);}cd[w_i]=seen.size;}result[acts[a_i]]=cd;}
    return{weeks,activities:acts,data:result};
  }
  apiSummary(m){
    const mi=this.cat['month'],bi=this.cat['biz_group'],ci=this.cat['category'],si=this.cat['sku'],li=this.cat['listing'];const months=this.meta.lookups['month'];
    const sc=['SPEND$','Total ads Sales$','Total ads Orders','Total ads Units','Advertised SKU Sales$','IMPRESSIONS','CLICKS','页面浏览次数','已订购商品数量','已订购商品销售额','RRP','实际成交价','促销费','funding_num'];
    const groups=new Map();
    for(let i=0;i<this.nRows;i++){if(!m[i])continue;const k=mi[i]+'_'+bi[i]+'_'+ci[i];if(!groups.has(k)){const s={};for(const c of sc)s[c]=0;groups.set(k,{mi:mi[i],bi:bi[i],ci:ci[i],s,sk:new Set(),li:new Set()});}const g=groups.get(k);for(const c of sc)g.s[c]+=this.num[c][i];g.sk.add(si[i]);g.li.add(li[i]);}
    const prev={};const rows=[];const keys=Array.from(groups.keys()).sort((a,b)=>{const[am,ab,ac]=a.split('_').map(Number);const[bm,bb,bc]=b.split('_').map(Number);return am!==bm?am-bm:(ab!==bb?ab-bb:ac-bc);});
    for(const k of keys){const g=groups.get(k);const mt=this.metrics(g.s);const bc=g.bi+'_'+g.ci;const p=prev[bc];
      rows.push({'月':months[g.mi],'业务组':this.meta.lookups['biz_group'][g.bi],'三级分类':this.meta.lookups['category'][g.ci],'最早SKU去重计数':g.sk.size,'Listing标识去重计数':g.li.size,'SPEND$':Math.round(g.s['SPEND$']*100)/100,'Total ads Sales$':Math.round(g.s['Total ads Sales$']*100)/100,'Total ads Units':Math.round(g.s['Total ads Units']),'IMPRESSIONS':Math.round(g.s['IMPRESSIONS']),'CLICKS':Math.round(g.s['CLICKS']),'页面浏览次数':Math.round(g.s['页面浏览次数']),'已订购商品数量':Math.round(g.s['已订购商品数量']),'已订购商品销售额':Math.round(g.s['已订购商品销售额']*100)/100,...mt,'SPEND$环比%':p?this.hb(g.s['SPEND$'],p['SPEND$']):0,'已订购商品数量环比%':p?this.hb(g.s['已订购商品数量'],p['已订购商品数量']):0,'Total ads Units环比%':p?this.hb(g.s['Total ads Units'],p['Total ads Units']):0});
      prev[bc]=g.s;
    }
    return{rows};
  }
  apiDiscountSummary(m){
    const mi=this.cat['month'],dti=this.cat['discount_tag'],si=this.cat['sku'],li=this.cat['listing'];const months=this.meta.lookups['month'];const tags=this.meta.lookups['discount_tag'];
    const order=['<0','①0-10%','②10%-15%','③15%-20%','④20%-25%','⑤25%-30%','⑥30%+','0'];const sorted=order.filter(t=>tags.includes(t)).concat(tags.filter(t=>!order.includes(t)));
    const sc=['SPEND$','Total ads Sales$','Total ads Orders','Total ads Units','Advertised SKU Sales$','IMPRESSIONS','CLICKS','页面浏览次数','已订购商品数量','已订购商品销售额','RRP','实际成交价','促销费','funding_num'];
    const groups=new Map();
    for(let i=0;i<this.nRows;i++){if(!m[i])continue;const k=mi[i]+'_'+dti[i];if(!groups.has(k)){const s={};for(const c of sc)s[c]=0;groups.set(k,{mi:mi[i],dti:dti[i],s,sk:new Set(),li:new Set()});}const g=groups.get(k);for(const c of sc)g.s[c]+=this.num[c][i];g.sk.add(si[i]);g.li.add(li[i]);}
    const rows=[];const prev={};
    for(let m_i=0;m_i<months.length;m_i++){for(const dn of sorted){const di=tags.indexOf(dn);if(di<0)continue;const g=groups.get(m_i+'_'+di);if(!g)continue;const mt=this.metrics(g.s);const p=prev[dn];
      rows.push({'月':months[m_i],'折扣打标':dn,'最早SKU去重计数':g.sk.size,'Listing标识去重计数':g.li.size,'SPEND$':Math.round(g.s['SPEND$']*100)/100,'Total ads Sales$':Math.round(g.s['Total ads Sales$']*100)/100,'Total ads Units':Math.round(g.s['Total ads Units']),'IMPRESSIONS':Math.round(g.s['IMPRESSIONS']),'CLICKS':Math.round(g.s['CLICKS']),'页面浏览次数':Math.round(g.s['页面浏览次数']),'已订购商品数量':Math.round(g.s['已订购商品数量']),'已订购商品销售额':Math.round(g.s['已订购商品销售额']*100)/100,...mt,'SPEND$环比%':p?this.hb(g.s['SPEND$'],p['SPEND$']):0,'已订购商品数量环比%':p?this.hb(g.s['已订购商品数量'],p['已订购商品数量']):0,'Total ads Units环比%':p?this.hb(g.s['Total ads Units'],p['Total ads Units']):0});
      prev[dn]=g.s;
    }}
    return{rows};
  }
  _fi(lk,v){return this.meta.lookups[lk]?this.meta.lookups[lk].indexOf(v):-1;}
  apiPromoSummary(m){
    const mi=this.cat['month'],bi=this.cat['biz_group'],ci=this.cat['category'],si=this.cat['sku'];const months=this.meta.lookups['month'];
    const cm={'活动计数':{k:'is_activity',i:this._fi('is_activity','活动')},'比低价计数':{k:'price_type',i:this._fi('price_type','比低价')},'比高价计数':{k:'price_type',i:this._fi('price_type','比高价')},'BD标识计数':{k:'activity',i:this._fi('activity','BD')},'VM BD标识计数':{k:'activity',i:this._fi('activity','VM BD')},'比例一致计数':{k:'ratio_compare',i:this._fi('ratio_compare','比例一致')},'funding更高计数':{k:'ratio_compare',i:this._fi('ratio_compare','funding更高')},'funding更低计数':{k:'ratio_compare',i:this._fi('ratio_compare','funding更低')}};
    const groups=new Map();const cg={};for(const cn of Object.keys(cm))cg[cn]=new Map();
    for(let i=0;i<this.nRows;i++){if(!m[i])continue;const k=mi[i]+'_'+bi[i]+'_'+ci[i];if(!groups.has(k))groups.set(k,{mi:mi[i],bi:bi[i],ci:ci[i],sk:new Set()});groups.get(k).sk.add(si[i]);for(const[cn,cd]of Object.entries(cm)){if(cd.i<0)continue;if(this.cat[cd.k][i]===cd.i){if(!cg[cn].has(k))cg[cn].set(k,new Set());cg[cn].get(k).add(si[i]);}}}
    const rows=[];const keys=Array.from(groups.keys()).sort((a,b)=>{const[am,ab,ac]=a.split('_').map(Number);const[bm,bb,bc]=b.split('_').map(Number);return am!==bm?am-bm:(ab!==bb?ab-bb:ac-bc);});
    for(const k of keys){const g=groups.get(k);const row={'月':months[g.mi],'业务组':this.meta.lookups['biz_group'][g.bi],'三级分类':this.meta.lookups['category'][g.ci],'最早SKU去重计数':g.sk.size};for(const cn of Object.keys(cm)){const s=cg[cn].get(k);row[cn]=s?s.size:0;}rows.push(row);}
    return{rows};
  }
  apiListingSummary(m){
    const mi=this.cat['month'],bi=this.cat['biz_group'],ci=this.cat['category'],si=this.cat['sku'],li=this.cat['listing'],lmi=this.cat['listing_month'];const months=this.meta.lookups['month'];const lms=this.meta.lookups['listing_month'];
    const cm={'活动计数':{k:'is_activity',i:this._fi('is_activity','活动')},'比低价计数':{k:'price_type',i:this._fi('price_type','比低价')},'比高价计数':{k:'price_type',i:this._fi('price_type','比高价')},'BD标识计数':{k:'activity',i:this._fi('activity','BD')},'VM BD标识计数':{k:'activity',i:this._fi('activity','VM BD')},'比例一致计数':{k:'ratio_compare',i:this._fi('ratio_compare','比例一致')},'funding更高计数':{k:'ratio_compare',i:this._fi('ratio_compare','funding更高')},'funding更低计数':{k:'ratio_compare',i:this._fi('ratio_compare','funding更低')}};
    const groups=new Map();const cg={};for(const cn of Object.keys(cm))cg[cn]=new Map();
    for(let i=0;i<this.nRows;i++){if(!m[i])continue;const k=mi[i]+'_'+bi[i]+'_'+ci[i]+'_'+lmi[i];if(!groups.has(k))groups.set(k,{mi:mi[i],bi:bi[i],ci:ci[i],lmi:lmi[i],sk:new Set(),li:new Set()});const g=groups.get(k);g.sk.add(si[i]);g.li.add(li[i]);for(const[cn,cd]of Object.entries(cm)){if(cd.i<0)continue;if(this.cat[cd.k][i]===cd.i){if(!cg[cn].has(k))cg[cn].set(k,new Set());cg[cn].get(k).add(si[i]);}}}
    const rows=[];const keys=Array.from(groups.keys()).sort((a,b)=>{const pa=a.split('_').map(Number);const pb=b.split('_').map(Number);for(let j=0;j<4;j++)if(pa[j]!==pb[j])return pa[j]-pb[j];return 0;});
    for(const k of keys){const g=groups.get(k);const row={'月':months[g.mi],'业务组':this.meta.lookups['biz_group'][g.bi],'三级分类':this.meta.lookups['category'][g.ci],'最早SKU去重计数':g.sk.size,'Listing标识去重计数':g.li.size,'上架年月':lms[g.lmi]};for(const cn of Object.keys(cm)){const s=cg[cn].get(k);row[cn]=s?s.size:0;}rows.push(row);}
    return{rows};
  }
  apiCatFundingTrend(m){
    const wi=this.cat['week'],ci=this.cat['category'];const weeks=this.meta.lookups['week'];const cats=this.meta.lookups['category'].filter(v=>v&&v!=='nan'&&v!=='0');
    const groups=new Map();
    for(let i=0;i<this.nRows;i++){if(!m[i])continue;const k=wi[i]+'_'+ci[i];if(!groups.has(k))groups.set(k,{rrp:0,fund:0});groups.get(k).rrp+=this.num['RRP'][i];groups.get(k).fund+=this.num['funding_num'][i];}
    const datasets=[];
    for(const cat of cats){const c_i=this.meta.lookups['category'].indexOf(cat);const data=new Array(weeks.length).fill(0);for(let w=0;w<weeks.length;w++){const g=groups.get(w+'_'+c_i);if(g)data[w]=Math.round(this.sd(g.fund,g.rrp)*1e4)/100;}datasets.push({label:cat,data});}
    return{weeks,datasets};
  }
  apiSkuFundingTrend(m){
    const wi=this.cat['week'],si=this.cat['sku'];const weeks=this.meta.lookups['week'];const skus=this.meta.lookups['sku'];
    const cnt=new Map();for(let i=0;i<this.nRows;i++){if(!m[i])continue;cnt.set(si[i],(cnt.get(si[i])||0)+1);}
    const top=Array.from(cnt.entries()).sort((a,b)=>b[1]-a[1]).slice(0,30).map(e=>e[0]);
    const groups=new Map();
    for(let i=0;i<this.nRows;i++){if(!m[i]||!top.includes(si[i]))continue;const k=wi[i]+'_'+si[i];if(!groups.has(k))groups.set(k,{rrp:0,fund:0});groups.get(k).rrp+=this.num['RRP'][i];groups.get(k).fund+=this.num['funding_num'][i];}
    const datasets=[];
    for(const idx of top){const data=[];for(let w=0;w<weeks.length;w++){const g=groups.get(w+'_'+idx);data.push(g?Math.round(this.sd(g.fund,g.rrp)*1e4)/100:0);}datasets.push({label:skus[idx],data});}
    return{weeks,datasets};
  }
  apiDiscountTrend(m){
    const wi=this.cat['week'],dti=this.cat['discount_tag'],si=this.cat['sku'];const weeks=this.meta.lookups['week'];const tags=this.meta.lookups['discount_tag'];
    const order=['<0','①0-10%','②10%-15%','③15%-20%','④20%-25%','⑤25%-30%','⑥30%+','0'];const sorted=order.filter(t=>tags.includes(t)).concat(tags.filter(t=>!order.includes(t)));
    const datasets=[];
    for(const dn of sorted){const di=tags.indexOf(dn);const data=[];for(let w=0;w<weeks.length;w++){const seen=new Set();for(let i=0;i<this.nRows;i++){if(m[i]&&wi[i]===w&&dti[i]===di)seen.add(si[i]);}data.push(seen.size);}datasets.push({label:dn,data});}
    return{weeks,datasets};
  }
  apiSkuDetail(mask,params){
    const td=params.time_dim||'day';const tk=td==='week'?'week':td==='month'?'month':'day';
    const ti=this.cat[tk],si=this.cat['sku'],li=this.cat['listing'];const times=this.meta.lookups[tk];const skus=this.meta.lookups['sku'];
    let fm=mask;
    const ts=params[tk];if(ts){const sv=ts.split(',').map(s=>s.trim()).filter(s=>s);const si2=new Set();for(const v of sv){const idx=times.indexOf(v);if(idx>=0)si2.add(idx);}const tm=new Uint8Array(this.nRows);for(let i=0;i<this.nRows;i++)if(si2.has(ti[i]))tm[i]=1;const nm=new Uint8Array(this.nRows);for(let i=0;i<this.nRows;i++)nm[i]=fm[i]&&tm[i];fm=nm;}
    const sc=['RRP','实际成交价','理论成交价','funding_num','Total ads Units','SPEND$','Total ads Sales$','Total ads Orders','Advertised SKU Sales$','IMPRESSIONS','CLICKS','页面浏览次数','已订购商品数量','已订购商品销售额','促销费'];
    const groups=new Map();
    for(let i=0;i<this.nRows;i++){if(!fm[i])continue;const k=ti[i]+'_'+si[i];if(!groups.has(k)){const s={};for(const c of sc)s[c]=0;groups.set(k,{ti:ti[i],si:si[i],s,li:li[i],pt:this.cat['price_type'][i],ia:this.cat['is_activity'][i],act:this.cat['activity'][i]});}const g=groups.get(k);for(const c of sc)g.s[c]+=this.num[c][i];}
    const et=new Map();for(const[k,g]of groups){if(!et.has(g.si))et.set(g.si,[]);et.get(g.si).push({ti:g.ti,k});}
    for(const[ei,tl]of et)tl.sort((a,b)=>a.ti-b.ti);
    const rows=[];let cnt=0;const mx=5000;
    for(const[k,g]of groups){if(cnt>=mx)break;const a=g.s;const mt=this.metrics(a);const tl=et.get(g.si);const ci=tl.findIndex(t=>t.k===k);let hs=0,ho=0,hu=0;if(ci>0){const pg=groups.get(tl[ci-1].k);if(pg){hs=this.hb(a['SPEND$'],pg.s['SPEND$']);ho=this.hb(a['已订购商品数量'],pg.s['已订购商品数量']);hu=this.hb(a['Total ads Units'],pg.s['Total ads Units']);}}
      rows.push({'时间':times[g.ti],'Listing标识':this.meta.lookups['listing'][g.li],'最早SKU':skus[g.si],'RRP':Math.round(a['RRP']*100)/100,'实际成交价':Math.round(a['实际成交价']*100)/100,'理论成交价':Math.round(a['理论成交价']*100)/100,'比价类型':this.meta.lookups['price_type'][g.pt],'是否活动':this.meta.lookups['is_activity'][g.ia],'活动标识':this.meta.lookups['activity'][g.act],'funding':Math.round(a['funding_num']*100)/100,'Total ads Units':Math.round(a['Total ads Units']),'Total ads Units环比%':hu,'SPEND$':Math.round(a['SPEND$']*100)/100,'SPEND$环比%':hs,'Total ads Sales$':Math.round(a['Total ads Sales$']*100)/100,'Total ads Orders':Math.round(a['Total ads Orders']),'IMPRESSIONS':Math.round(a['IMPRESSIONS']),'CLICKS':Math.round(a['CLICKS']),'页面浏览次数':Math.round(a['页面浏览次数']),'已订购商品数量':Math.round(a['已订购商品数量']),'已订购商品数量环比%':ho,'已订购商品销售额':Math.round(a['已订购商品销售额']*100)/100,...mt});cnt++;}
    if(cnt>=mx)rows.push({_truncated:true});return{rows};
  }
  apiListingDetail(mask,params){
    const td=params.time_dim||'day';const tk=td==='week'?'week':td==='month'?'month':'day';
    const ti=this.cat[tk],si=this.cat['sku'],li=this.cat['listing'];const times=this.meta.lookups[tk];const listings=this.meta.lookups['listing'];
    let fm=mask;
    const ts=params[tk];if(ts){const sv=ts.split(',').map(s=>s.trim()).filter(s=>s);const si2=new Set();for(const v of sv){const idx=times.indexOf(v);if(idx>=0)si2.add(idx);}const tm=new Uint8Array(this.nRows);for(let i=0;i<this.nRows;i++)if(si2.has(ti[i]))tm[i]=1;const nm=new Uint8Array(this.nRows);for(let i=0;i<this.nRows;i++)nm[i]=fm[i]&&tm[i];fm=nm;}
    const sc=['RRP','实际成交价','理论成交价','funding_num','Total ads Units','SPEND$','Total ads Sales$','Total ads Orders','Advertised SKU Sales$','IMPRESSIONS','CLICKS','页面浏览次数','已订购商品数量','已订购商品销售额','促销费'];
    const groups=new Map();
    for(let i=0;i<this.nRows;i++){if(!fm[i])continue;const k=ti[i]+'_'+li[i];if(!groups.has(k)){const s={};for(const c of sc)s[c]=0;groups.set(k,{ti:ti[i],li:li[i],s,skuCnt:new Set(),pt:this.cat['price_type'][i],ia:this.cat['is_activity'][i],act:this.cat['activity'][i]});}const g=groups.get(k);for(const c of sc)g.s[c]+=this.num[c][i];g.skuCnt.add(si[i]);}
    const et=new Map();for(const[k,g]of groups){if(!et.has(g.li))et.set(g.li,[]);et.get(g.li).push({ti:g.ti,k});}
    for(const[ei,tl]of et)tl.sort((a,b)=>a.ti-b.ti);
    const rows=[];let cnt=0;const mx=5000;
    for(const[k,g]of groups){if(cnt>=mx)break;const a=g.s;const mt=this.metrics(a);const tl=et.get(g.li);const ci=tl.findIndex(t=>t.k===k);let hs=0,ho=0,hu=0;if(ci>0){const pg=groups.get(tl[ci-1].k);if(pg){hs=this.hb(a['SPEND$'],pg.s['SPEND$']);ho=this.hb(a['已订购商品数量'],pg.s['已订购商品数量']);hu=this.hb(a['Total ads Units'],pg.s['Total ads Units']);}}
      rows.push({'时间':times[g.ti],'Listing标识':listings[g.li],'最早SKU去重计数':g.skuCnt.size,'RRP':Math.round(a['RRP']*100)/100,'实际成交价':Math.round(a['实际成交价']*100)/100,'理论成交价':Math.round(a['理论成交价']*100)/100,'比价类型':this.meta.lookups['price_type'][g.pt],'是否活动':this.meta.lookups['is_activity'][g.ia],'活动标识':this.meta.lookups['activity'][g.act],'funding':Math.round(a['funding_num']*100)/100,'Total ads Units':Math.round(a['Total ads Units']),'Total ads Units环比%':hu,'SPEND$':Math.round(a['SPEND$']*100)/100,'SPEND$环比%':hs,'Total ads Sales$':Math.round(a['Total ads Sales$']*100)/100,'Total ads Orders':Math.round(a['Total ads Orders']),'IMPRESSIONS':Math.round(a['IMPRESSIONS']),'CLICKS':Math.round(a['CLICKS']),'页面浏览次数':Math.round(a['页面浏览次数']),'已订购商品数量':Math.round(a['已订购商品数量']),'已订购商品数量环比%':ho,'已订购商品销售额':Math.round(a['已订购商品销售额']*100)/100,...mt});cnt++;}
    if(cnt>=mx)rows.push({_truncated:true});return{rows};
  }
}
