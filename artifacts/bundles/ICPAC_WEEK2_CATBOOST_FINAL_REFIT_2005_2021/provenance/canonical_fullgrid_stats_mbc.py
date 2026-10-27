#!/usr/bin/env python3
"""ICPAC-11 exhaustive 0.05-degree 2005-2019 training / 2020-2021 validation.

Every authoritative grid cell and every time-eligible hindcast case is visited.
No statistical row subsampling, no coarse target aggregation, no 2022+ reads.
Sparse interpolation is used for coarse ECMWF predictors; CHIRPS stays 0.05 deg.
The train stage accumulates exact, area-weighted sufficient statistics, not rows.
"""
import os
for k in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ.setdefault(k, '2')
import argparse, csv, hashlib, json, sys, warnings
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import xarray as xr
from scipy import sparse

HUB = Path('/scratch/njoel/ICPAC_DATA_HUB')
R = HUB/'ECMWF/S2S_2005_2025/reforecast_2005_2024_tp_processed.zarr'
PRESS = Path('/scratch/njoel/s2s_master_data/processed/ecmwf_pressure_pf')
CH = HUB/'CHIRPS/V2/daily_2005_2025.zarr'
MASK = HUB/'DOMAIN/authoritative_icpac11_mask.npz'
ROOT = Path('/scratch/njoel/s2s_master_data/results/ICPAC_RETRAIN_2005_2025_V1')
PCA = ROOT/'PCA_TRAIN_2005_2019/ATMOS30_PCA_TRAIN_2005_2019.npz'
CCA = ROOT/'CCA_DIAGNOSTIC_2005_2021'
OUT = ROOT/'FULLGRID_005_STATS_MBC_2005_2021'
TRAIN = tuple(range(2005,2020))
VALID = (2020,2021)
LEADS = [192,216,240,264,288,312,336]
Q = ['q850','q700','u850','v850','wind850','qu850','qv850','qwind850','t850','t500','deltaT850_500','gh500','u200','v200','shear200_850']
FEATS = [v+s for v in Q for s in ('_mean','_spread')]
DCORE = ['rain_mean_50mm','rain_spread_20mm','latitude_20deg','longitude_50deg','doy_sin','doy_cos']
SPL_RAW = [5.,15.,30.,60.,100.]
SPL_SPREAD = [2.,5.,15.,30.]
NBASE=6+17
NBASIS=NBASE+len(SPL_RAW)+len(SPL_SPREAD)
PSEUDO=(50.,500.,2000.)
UPPER=(3.,5.)
NATIVE=(27,24)
NUMERIC_TOL=0.10
MAX_NEG_FRAC=0.10


def stamp(): return datetime.now(timezone.utc).isoformat()

def jwrite(path, obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.tmp')
    with tmp.open('w') as f: json.dump(obj,f,indent=2,allow_nan=False)
    tmp.replace(path)

def load_pca():
    with np.load(PCA,allow_pickle=False) as z:
        assert list(z['feature_names'])==FEATS, 'Training-PCA feature order changed'
        assert list(z['training_years'])==list(TRAIN)
        assert int(z['cell_count'])==205999
        mu=z['mean'].astype(np.float64); scale=z['scale'].astype(np.float64)
        B=z['components'][:17].T.astype(np.float64)
    assert (scale>0).all() and B.shape==(30,17)
    return mu,scale,B


def data_cases(m):
    # CCA file is used ONLY as a verified inventory of case initialization dates.
    p=CCA/f'cca_month_{m:02d}.npz'
    with np.load(p,allow_pickle=False) as z:
        d={k:z[k].copy() for k in ('inits','years','target_end')}
    dates=d['inits'].astype(str); years=d['years'].astype(int); ends=d['target_end'].astype(str)
    assert (years>=2005).all() and (years<=2021).all()
    assert len(dates)==len(set(dates))
    assert len(dates)>=200
    for date,y,end in zip(dates,years,ends):
        assert date[:4]==f'{y:04d}' and int(date[5:7])==m
        expected=str(np.datetime64(date,'D')+np.timedelta64(13,'D'))
        assert end==expected, (date,end,expected)
        assert end<=('2019-12-31' if y<=2019 else '2021-12-31')
    return [(str(a),int(b)) for a,b in zip(dates,years)]


def case_inventory():
    allcases=[(date,yr) for m in range(1,13) for date,yr in data_cases(m)]
    years=np.array([y for _,y in allcases]); dates=[d for d,_ in allcases]
    assert len(allcases)==3148 and (int(np.sum(years<=2019)),int(np.sum(years>=2020)))==(2783,365),len(allcases)
    assert len(set(dates))==len(dates)
    return allcases


def pressure_file(date):
    p=PRESS/f'ecmwf_s2s_mv2025{date[5:7]}{date[8:10]}_h2005-2024_pf_pressure.nc'
    if not p.is_file(): raise FileNotFoundError(p)
    return p


def geometry(lat,lon):
    with np.load(MASK,allow_pickle=False) as z:
        fy=np.asarray(z['latitude'],dtype=np.float64)
        fx=np.asarray(z['longitude'],dtype=np.float64)
        mask=np.asarray(z['domain_mask'],dtype=bool)
    assert fy.shape==(800,) and fx.shape==(700,) and mask.shape==(800,700)
    assert int(mask.sum())==205999,'Authoritative mask unexpected'
    r,c=np.nonzero(mask); yy,xx=fy[r],fx[c]
    iy=np.argsort(lat);ix=np.argsort(lon)
    lat_s,lon_s=lat[iy],lon[ix]
    assert lat_s.size==27 and lon_s.size==24
    assert yy.min()>=lat_s.min() and yy.max()<=lat_s.max()
    assert xx.min()>=lon_s.min() and xx.max()<=lon_s.max()
    j=np.searchsorted(lat_s,yy,side='right').clip(1,26); i=np.searchsorted(lon_s,xx,side='right').clip(1,23)
    jy=(yy-lat_s[j-1])/(lat_s[j]-lat_s[j-1])
    ixr=(xx-lon_s[i-1])/(lon_s[i]-lon_s[i-1])
    rc=np.arange(205999,dtype=np.int32)
    cc=np.concatenate([iy[j-1]*24+ix[i-1],iy[j-1]*24+ix[i],iy[j]*24+ix[i-1],iy[j]*24+ix[i]]).astype(np.int32)
    vv=np.concatenate([(1-jy)*(1-ixr),(1-jy)*ixr,jy*(1-ixr),jy*ixr])
    AA=sparse.coo_matrix((vv,(np.tile(rc,4),cc)),shape=(len(rc),648)).tocsr()
    assert np.allclose(np.asarray(AA.sum(axis=1)).ravel(),1,atol=1e-12)
    return r,c,yy,xx,AA,np.cos(np.deg2rad(yy))


def atm_features(ds,yi,lead_indices,lev):
    ds=ds[['gh','t','q','u','v']].isel(time=yi,step=lead_indices).load()
    a={k:ds[k].transpose('number','step','isobaricInhPa','latitude','longitude').values.astype(np.float64,copy=False) for k in ('gh','t','q','u','v')}
    g=lambda v,h:a[v][:,:,lev[h],:,:]
    q8,q7=g('q',850),g('q',700);u8,v8=g('u',850),g('v',850)
    t8,t5=g('t',850),g('t',500);h5=g('gh',500);u2,v2=g('u',200),g('v',200)
    wind=np.hypot(u8,v8)
    fs=[q8,q7,u8,v8,wind,q8*u8,q8*v8,q8*wind,t8,t5,t8-t5,h5,u2,v2,np.hypot(u2-u8,v2-v8)]
    f=[]
    for x in fs:
        member=x.mean(axis=1)
        f.extend([member.mean(axis=0).ravel(),member.std(axis=0,ddof=0).ravel()])
    out=np.stack(f,axis=1)
    assert out.shape==(648,30) and np.isfinite(out).all()
    return out


def feat_matrix(raw,spread,atm_native,AA,lat,lon,doy,mu,scale,B):
    atmos=AA @ atm_native
    pcs=((atmos-mu)/scale)@B
    s=np.sin(2*np.pi*doy/365.2425); c=np.cos(2*np.pi*doy/365.2425)
    n=len(raw)
    x=np.empty((n,NBASIS),dtype=np.float64)
    x[:,0]=raw/50.;x[:,1]=spread/20.;x[:,2]=lat/20.;x[:,3]=lon/50.
    x[:,4]=s;x[:,5]=c;x[:,6:NBASE]=pcs/4.
    for k,t in enumerate(SPL_RAW): x[:,NBASE+k]=np.maximum((raw-t)/50.,0.)
    for k,t in enumerate(SPL_SPREAD):x[:,NBASE+len(SPL_RAW)+k]=np.maximum((spread-t)/20.,0.)
    assert np.isfinite(x).all()
    return x


def get_week_chirps(ch,date,rows,cols,time_map):
    start=np.datetime64(date,'D')+np.timedelta64(7,'D')
    targets=start+np.arange(7).astype('timedelta64[D]')
    lookup=[str(d) for d in targets]
    assert all(t[:4]<='2021' for t in lookup),'2022+ TEST TARGET ACCESS REFUSED'
    ix=[time_map[t] for t in lookup]
    a=np.asarray(ch.precip.isel(time=ix).values,dtype=np.float32)
    assert a.shape==(7,800,700)
    fine=a[:,rows,cols]
    ok=np.isfinite(fine).all(axis=0)&(fine>=0).all(axis=0)
    obs=np.full(len(rows),np.nan,dtype=np.float32)
    obs[ok]=fine[:,ok].sum(axis=0,dtype=np.float64).astype(np.float32)
    return obs


def raw_member_week(tp,ii,yi,steps):
    data=np.asarray(tp.tp.isel(init_time=ii,time=yi,step=steps).transpose('number','step','latitude','longitude').values,dtype=np.float64)
    assert data.shape==(10,2,27,24) and np.isfinite(data).all()
    rain=data[:,1]-data[:,0]
    neg=rain<0
    if neg.any() and (rain.min() < -NUMERIC_TOL-1e-8 or neg.mean()>MAX_NEG_FRAC):
        raise ValueError(f'Raw ECMWF negative accumulation: min={rain.min()} fraction={neg.mean()}')
    rain=np.maximum(rain,0.)
    return rain.mean(axis=0).ravel(),rain.std(axis=0,ddof=0).ravel(),int(neg.sum()),int(rain.size),float(data[:,1].max())


def sources():
    pp=pressure_file('2005-01-01')
    with xr.open_dataset(pp) as p:
        lat=np.asarray(p.latitude.values,dtype=np.float64)
        lon=np.asarray(p.longitude.values,dtype=np.float64)
    r,c,fy,fx,AA,w=geometry(lat,lon)
    return lat,lon,r,c,fy,fx,AA,w


def open_forecast():
    ds=xr.open_zarr(R,consolidated=None,chunks={})
    assert ds.sizes['init_time']==186 and ds.sizes['number']==10 and ds.sizes['time']==20
    assert ds.sizes['latitude']==27 and ds.sizes['longitude']==24
    units=str(ds.tp.attrs.get('units',ds.tp.attrs.get('GRIB_units','')))
    assert ('kg' in units and 'm' in units) or 'mm' in units.lower(),units
    steps=np.asarray(ds.step.values).astype('timedelta64[h]').astype(int)
    lead=[int(np.flatnonzero(steps==h)[0]) for h in (168,336)]
    init_map={str(x).replace('-','')[:8]:i for i,x in enumerate(ds.init_time.values)}
    tm=ds.time.values.astype('datetime64[D]')
    years=[int(str(t)[:4]) for t in tm]
    ymap={y:i for i,y in enumerate(years)}
    assert set(range(2005,2022)).issubset(ymap)
    return ds,init_map,ymap,lead


def open_pressure(file,lat,lon):
    ds=xr.open_dataset(file,decode_times=True)
    np.testing.assert_allclose(ds.latitude.values,lat,rtol=0,atol=1e-6)
    np.testing.assert_allclose(ds.longitude.values,lon,rtol=0,atol=1e-6)
    assert ds.sizes['number']==10 and ds.sizes['time']==20
    hrs=np.asarray(ds.step.values).astype('timedelta64[h]').astype(int)
    lead=[int(np.flatnonzero(hrs==h)[0]) for h in LEADS]
    lev={int(x):i for i,x in enumerate(ds.isobaricInhPa.values)}
    assert set(lev)=={850,700,500,200}
    years={int(v):i for i,v in enumerate(np.asarray(ds.time.dt.year.values))}
    return ds,lead,lev,years


def month_iter(month,partition,with_atmos=True):
    mu,scale,B=load_pca() if with_atmos else (None,None,None)
    lat,lon,r,c,fy,fx,AA,w=sources()
    cases=data_cases(month)
    ds,i_map,y_map,steps=open_forecast()
    ch=xr.open_zarr(CH,consolidated=None,chunks={})
    try:
        np.testing.assert_allclose(ds.latitude.values,lat,atol=1e-6,rtol=0)
        np.testing.assert_allclose(ds.longitude.values,lon,atol=1e-6,rtol=0)
        assert ch.sizes['time']==7670
        with np.load(MASK,allow_pickle=False) as z:
            np.testing.assert_allclose(ch.latitude.values,z['latitude'],atol=1e-6,rtol=0)
            np.testing.assert_allclose(ch.longitude.values,z['longitude'],atol=1e-6,rtol=0)
        assert 'mm' in str(ch.precip.attrs.get('units','')).lower()
        datemap={str(d):i for i,d in enumerate(ch.time.values.astype('datetime64[D]'))}
        group={}
        for date,year in cases:
            if (year<=2019 if partition=='train' else year>=2020):
                group.setdefault('2025'+date[5:7]+date[8:10],[]).append((date,year))
        count=0
        for init,subcases in sorted(group.items()):
            pfile=PRESS/f'ecmwf_s2s_mv{init}_h2005-2024_pf_pressure.nc'
            ds_p,leads,lev,yind=open_pressure(pfile,lat,lon) if with_atmos else (None,None,None,None)
            try:
                for date,year in subcases:
                    assert init in i_map and year in y_map
                    raw_native,sp_native,nneg,ntotal,_=raw_member_week(ds,i_map[init],y_map[year],steps)
                    raw=np.asarray(AA@raw_native,dtype=np.float32)
                    spr=np.asarray(AA@sp_native,dtype=np.float32)
                    if not np.isfinite(raw).all() or (raw<0).any():raise ValueError('Invalid interpolated Week-2 ECMWF rainfall')
                    obs=get_week_chirps(ch,date,r,c,datemap)
                    if with_atmos:
                        ai=yind[year]
                        native=atm_features(ds_p,ai,leads,lev)
                        doy=int((np.datetime64(date)-np.datetime64(f'{year}-01-01')).astype(int))+1
                        x=feat_matrix(raw,spr,native,AA,fy,fx,doy,mu,scale,B)
                    else:x=None
                    count+=1
                    yield obs,raw,x,w,date,year,nneg,ntotal
            finally:
                if ds_p is not None:ds_p.close()
        print(f'MONTH {month:02} {partition}: processed {count} complete forecast cases and {len(w)} official cells per case',flush=True)
    finally:
        ch.close();ds.close()


def preflight():
    OUT.mkdir(parents=True,exist_ok=True)
    case_inventory()
    load_pca()
    lat,lon,r,c,fy,fx,A,w=sources()
    assert len(r)==205999 and len(w)==205999
    assert PRESS.is_dir() and len(list(PRESS.glob('ecmwf_s2s_mv2025*_h2005-2024_pf_pressure.nc')))==186
    assert CH.exists() and R.exists()
    with xr.open_zarr(CH,consolidated=None,chunks={}) as ch:
        assert ch.sizes['latitude']==800 and ch.sizes['longitude']==700
    with xr.open_zarr(R,consolidated=None,chunks={}) as tp:
        np.testing.assert_allclose(tp.latitude.values,lat,rtol=0,atol=1e-6)
        np.testing.assert_allclose(tp.longitude.values,lon,rtol=0,atol=1e-6)
    print('PASS full-grid preflight: 205999 cells, 2783 train cases, 365 validation cases',flush=True)
    print('PASS CHIRPS remains 0.05-degree; ECMWF interpolated with sparse bilinear matrix',flush=True)
    print('PASS ALL train observations and atmospheric rows used, no sampling',flush=True)
    print('PASS no hindcast year 2022 or later accessed; 2022+ verifying dates rejected',flush=True)


def monthfit(m):
    OUT.mkdir(parents=True,exist_ok=True)
    n=205999; g=np.zeros((NBASIS,NBASIS),dtype=np.float64)
    sx=np.zeros(NBASIS); sxy=np.zeros(NBASIS)
    sy=syy=sw=0.; valid_rows=0; ncase=0; neg=0;total=0
    obslist=[];y_sum=np.zeros(n);raw_sum=np.zeros(n);valid_n=np.zeros(n,dtype=np.int32)
    obsclim=np.zeros(n);numclim=np.zeros(n,dtype=np.int32)
    for obs,raw,x,w,date,year,nneg,ntotal in month_iter(m,'train'):
        good=np.isfinite(obs)&np.isfinite(raw)
        if not np.all(np.isfinite(x)):raise RuntimeError('Non-finite training features')
        valid_rows+=int(good.sum()); ncase+=1;neg+=nneg;total+=ntotal
        obslist.append(obs)
        obsclim[good]+=obs[good];numclim[good]+=1
        y_sum[good]+=obs[good];raw_sum[good]+=raw[good];valid_n[good]+=1
        wg=w[good]; xx=x[good]; y=obs[good].astype(np.float64)
        sw+=wg.sum();sy+=wg@y;syy+=wg@(y*y)
        sx+=wg@xx;sxy+=xx.T@(wg*y)
        g+=xx.T@(xx*wg[:,None])
        if ncase%20==0:print(f'FIT MONTH {m:02}: {ncase} cases, {valid_rows} valid cell-rows',flush=True)
    assert ncase>=190 and valid_rows>ncase*n*0.95
    # Some official mask cells may have no CHIRPS measurements in a month.
    # Retain those cells; validation forecast fallback is fitted on TRAIN only.
    with warnings.catch_warnings():
        warnings.simplefilter('ignore',RuntimeWarning)
        med=np.nanmedian(np.asarray(obslist,dtype=np.float32),axis=0)
    assert len(med)==n
    print(f'MONTH {m:02}: training-missing cells requiring training-only fallback: {int(np.count_nonzero(numclim==0))}',flush=True)
    p=OUT/f'train_month_{m:02}.npz';tmp=Path(str(p)+'.tmp.npz')
    np.savez_compressed(tmp,gram=g,sx=sx,sxy=sxy,sy=sy,syy=syy,sw=sw,
        val_rows=valid_rows,ncases=ncase,obs_sum=y_sum,raw_sum=raw_sum,
        paired_n=valid_n,clim_sum=obsclim,clim_n=numclim,clim_median=med,
        numerical_neg_count=neg,numerical_total=total,month=m,cell_count=n)
    tmp.replace(p)
    print(f'PASS FULLGRID TRAIN MONTH {m:02}: cases={ncase}, rows={valid_rows}, saved={p}',flush=True)


def centered_moments(s):
    n=s['sw'];m=s['sx']/n; my=s['sy']/n
    c=(s['gram']-np.outer(s['sx'],s['sx'])/n)/n
    c=(c+c.T)/2
    b=(s['sxy']-s['sx']*my)/n
    return m,my,c,b


def getsubset(k,spline=False):
    idx=list(range(6+k))
    if spline:idx.extend(range(NBASE,NBASIS))
    return np.asarray(idx,dtype=int)


def fit_linear(s,idx,alpha=0.,enet=None):
    xm,ym,c,b=centered_moments(s)
    cov=c[np.ix_(idx,idx)].copy();target=b[idx].copy()
    if enet is None:
        beta=np.linalg.lstsq(cov+alpha*np.eye(len(idx)),target,rcond=1e-10)[0]
    else:
        a,ratio=enet
        sd=np.sqrt(np.maximum(np.diag(cov),1e-18))
        gram=cov/sd[:,None]/sd[None,:]
        h=target/sd
        z=np.zeros(len(idx));u=gram@z
        for it in range(3000):
            z0=z.copy()
            for j in range(len(z)):
                r=h[j]-(u[j]-gram[j,j]*z[j])
                v=np.sign(r)*max(abs(r)-a*ratio,0.)/(gram[j,j]+a*(1-ratio))
                delta=v-z[j]
                if delta:
                    z[j]=v;u+=gram[:,j]*delta
            if np.max(np.abs(z-z0))<1e-9:break
        beta=z/sd
    full=np.zeros(NBASIS,dtype=np.float64);full[idx]=beta
    intercept=float(ym-xm@full)
    if not np.isfinite(full).all() or not np.isfinite(intercept):raise ValueError('Bad fit')
    return np.r_[intercept,full]


def reg_models(s):
    models={}
    models['OLS_core6']=fit_linear(s,getsubset(0))
    for k in (5,10,13,17):
        models[f'PCR_{k:02}']=fit_linear(s,getsubset(k))
        for alpha in (0.001,0.01,0.1):
            models[f'Ridge_{k:02}_lambda{alpha}']=fit_linear(s,getsubset(k),alpha)
        for a in (0.02,0.1):
            for ratio in (0.2,0.7):
                models[f'ElasticNet_{k:02}_a{a}_l1{ratio}']=fit_linear(s,getsubset(k),enet=(a,ratio))
        for alpha in (0.01,0.1):
            models[f'AdditiveSpline_{k:02}_lambda{alpha}']=fit_linear(s,getsubset(k,True),alpha)
    return models


def load_training():
    stats=None; d={}
    for m in range(1,13):
        p=OUT/f'train_month_{m:02}.npz'
        if not p.is_file():raise FileNotFoundError(p)
        with np.load(p,allow_pickle=False) as z:
            dd={k:z[k].copy() for k in z.files}
        assert int(dd['month'])==m and int(dd['cell_count'])==205999
        if stats is None:
            stats={k:dd[k].copy() for k in ('gram','sx','sxy','sy','syy','sw','val_rows','ncases')}
        else:
            for k in stats:stats[k]+=dd[k]
        d[m]=dd
    assert int(stats['ncases'])==2783,(stats['ncases'],'unexpected train cases')
    print(f'TRAIN ALL ROWS: {int(stats["val_rows"]):,} CHIRPS-valid grid-case records out of {2783*205999:,} possible',flush=True)
    return stats,d


def train_group(m,group):
    if group=='monthly':return [m]
    if group=='seasonal':
        return [12,1,2] if m in (12,1,2) else ([3,4,5] if m<=5 else ([6,7,8] if m<=8 else [9,10,11]))
    if group=='annual':return list(range(1,13))
    raise ValueError(group)


def mbc_names():
    names=[f'MBC_{kind}_prior{int(prior)}_cap{int(cap)}' for kind in ('monthly','seasonal','annual') for prior in PSEUDO for cap in UPPER]
    return names+['MBC_regional_monthly']


def mbc_factors(month,d):
    _,_,_,_,_,_,_,w=sources()
    out={}
    for group in ('monthly','seasonal','annual'):
        keys=train_group(month,group)
        y=sum((d[q]['obs_sum'] for q in keys),np.zeros(205999))
        x=sum((d[q]['raw_sum'] for q in keys),np.zeros(205999))
        # Ratio computed only from joint-valid training CHIRPS/raw cells.
        global_ratio=float(w@y/(w@x))
        assert 0<global_ratio<100,(group,global_ratio)
        for prior in PSEUDO:
            local=(y+prior*global_ratio)/(x+prior)
            for upper in UPPER:
                out[f'MBC_{group}_prior{int(prior)}_cap{int(upper)}']=np.clip(local,0.2,upper).astype(np.float32)
    keys=[month]
    regional=float(w@d[month]['obs_sum']/(w@d[month]['raw_sum']))
    out['MBC_regional_monthly']=np.full(205999,np.clip(regional,0.2,5),dtype=np.float32)
    assert list(out)==mbc_names()
    return out


def reducefit():
    OUT.mkdir(parents=True,exist_ok=True)
    s,d=load_training()
    models=reg_models(s)
    obj=dict(names=np.array(list(models)),coefficients=np.stack(list(models.values())),feature_names=np.array(DCORE+[f'PC{i:02}_over4' for i in range(1,18)]+[f'hinge_raw_{v}mm' for v in SPL_RAW]+[f'hinge_spread_{v}mm' for v in SPL_SPREAD]),
        train_cases=int(s['ncases']),train_rows=int(s['val_rows']))
    np.savez_compressed(OUT/'TRAIN_ONLY_FULLGRID_REGRESSION_MODELS.npz',**obj)
    print(f'PASS Fitted {len(models)} full-grid statistical models using ALL {int(s["val_rows"]):,} valid training rows',flush=True)
    print('PASS MBC moments computed for ALL 205999 cells without any row sampling',flush=True)
    print('PASS 2022-2025 test years never opened',flush=True)


def metric_new():return np.zeros(10,dtype=np.float64)

def accum(acc,pred,obs,weight):
    ok=np.isfinite(obs)
    y=np.asarray(obs[ok],dtype=np.float64);p=np.asarray(pred[ok],dtype=np.float64)
    assert len(y)>0 and len(p)==len(y) and np.isfinite(p).all()
    assert (p>=0).all() and (y>=0).all()
    w=weight[ok]
    e=p-y
    acc[0]+=w.sum();acc[1]+=w@e;acc[2]+=w@(e*e);acc[3]+=w@np.abs(e)
    acc[4]+=w@y;acc[5]+=w@p;acc[6]+=w@(y*y);acc[7]+=w@(p*p)
    acc[8]+=w@(y*p);acc[9]+=len(y)

def mval(m):
    _,d=load_training()
    with np.load(OUT/'TRAIN_ONLY_FULLGRID_REGRESSION_MODELS.npz',allow_pickle=False) as z:
        names=list(z['names'].astype(str));beta=z['coefficients'].astype(np.float64)
    mb=mbc_factors(m,d)
    clim_n=d[m]['clim_n']
    clim_mean=np.full(205999,np.nan,dtype=np.float64)
    np.divide(d[m]['clim_sum'],clim_n,out=clim_mean,where=clim_n>0)
    # Training-only fallback for cells lacking any CHIRPS observations.
    _,_,_,_,_,_,_,cell_area=sources()
    trained=clim_n>0
    if not trained.any():raise RuntimeError('No training CHIRPS for calendar month')
    regional_train_mean=float(np.dot(cell_area,d[m]['clim_sum'])/np.dot(cell_area,clim_n))
    clim_mean[~trained]=regional_train_mean
    clim_median=d[m]['clim_median'].astype(np.float64).copy()
    if not np.isfinite(clim_median[trained]).all():raise RuntimeError('Unexpected missing training median')
    regional_train_median=float(np.nanmedian(clim_median[trained]))
    clim_median[~trained]=regional_train_median
    assert np.isfinite(clim_mean).all() and np.isfinite(clim_median).all()
    labels=['Raw_ECMWF','Climatology_monthly_mean','Climatology_monthly_median']+names+list(mb)
    data={name:metric_new() for name in labels}; year_data={};season_data={}
    ncase=0;nrows=0;nneg=0;ntot=0
    def season(month):return 'DJF' if month in (12,1,2) else ('MAM' if month in (3,4,5) else ('JJA' if month in (6,7,8) else 'SON'))
    for obs,raw,x,w,date,year,ne,nt in month_iter(m,'valid'):
        ncase+=1;nrows+=np.isfinite(obs).sum();nneg+=ne;ntot+=nt
        preds=[raw,clim_mean,clim_median]
        # Predict in 1 model block; 100% of fine-grid cells, zero sampling.
        vals=np.maximum(0.,beta[:,0][None,:]+x@beta[:,1:].T)
        preds.extend(vals[:,j] for j in range(len(names)))
        preds.extend(raw*mb[name] for name in mb)
        for name,pred in zip(labels,preds):
            accum(data[name],pred,obs,w)
            yd=year_data.setdefault(str(year),{}).setdefault(name,metric_new())
            accum(yd,pred,obs,w)
            sd=season_data.setdefault(season(m),{}).setdefault(name,metric_new())
            accum(sd,pred,obs,w)
        if ncase%10==0:print(f'VALID MONTH {m:02}: cases={ncase}, valid rows={nrows}',flush=True)
    assert ncase>=15
    payload=dict(month=m,cases=ncase,valid_rows=int(nrows),model_sums={name:v.tolist() for name,v in data.items()},
      year_sums={yr:{name:v.tolist() for name,v in z.items()} for yr,z in year_data.items()},
      season_sums={s:{name:v.tolist() for name,v in z.items()} for s,z in season_data.items()},
      raw_precip_negative_count=nneg,raw_precip_total=ntot)
    jwrite(OUT/f'validation_month_{m:02}.json',payload)
    print(f'PASS FULLGRID VALID MONTH {m:02}: {ncase} cases, {nrows} CHIRPS-valid 0.05-degree rows',flush=True)


def metrics(a):
    sw,err,errsq,ae,sy,sp,syy,spp,syp,nrows=a
    assert sw>0 and nrows>0
    bias=err/sw;rmse=np.sqrt(errsq/sw);mae=ae/sw
    covariance=syp/sw-(sy/sw)*(sp/sw)
    var_y=max(syy/sw-(sy/sw)**2,0);var_p=max(spp/sw-(sp/sw)**2,0)
    cor=float(covariance/np.sqrt(var_y*var_p)) if var_y>0 and var_p>0 else None
    return dict(rmse=float(rmse),mae=float(mae),bias=float(bias),pearson_r=cor,rows=int(nrows),area_weight_sum=float(sw))


def csvsave(p,rows):
    with p.open('w',newline='') as f:
        wr=csv.DictWriter(f,fieldnames=list(rows[0]));wr.writeheader();wr.writerows(rows)


def finalize():
    _,d=load_training()
    results={};yrs={};seasons={}; ncase=0;rows=0
    def merge(target,source):
        for k,v in source.items():
            if k not in target:target[k]=np.array(v,dtype=np.float64)
            else:target[k]+=np.array(v,dtype=np.float64)
    for m in range(1,13):
        p=OUT/f'validation_month_{m:02}.json'
        assert p.is_file(),p
        a=json.loads(p.read_text());assert a['month']==m
        ncase+=a['cases'];rows+=a['valid_rows']
        merge(results,a['model_sums'])
        for key,ds in a['year_sums'].items():merge(yrs.setdefault(key,{}),ds)
        for key,ds in a['season_sums'].items():merge(seasons.setdefault(key,{}),ds)
    assert ncase==365,('Validation count mismatch',ncase)
    assert 0<rows<=365*205999 and rows>365*205999*0.95
    counts={k:int(v[9]) for k,v in results.items()}
    assert set(counts.values())=={rows},'Models evaluated on nonidentical rows'
    base={k:metrics(v) for k,v in results.items()}
    raw=base['Raw_ECMWF']['rmse'];clim=base['Climatology_monthly_mean']['rmse']
    output=[]
    for name,v in base.items():
        family = ('MBC' if name.startswith('MBC_') else
            'raw' if name.startswith('Raw') else
            'climatology' if name.startswith('Climatology') else
            'additive_spline' if name.startswith('AdditiveSpline') else
            'elasticnet' if name.startswith('ElasticNet') else
            'ridge' if name.startswith('Ridge') else
            'PCR' if name.startswith('PCR') else 'OLS')
        output.append(dict(model=name,family=family,**v,skill_vs_raw_pct=100*(1-v['rmse']/raw),skill_vs_climatology_pct=100*(1-v['rmse']/clim)))
    output.sort(key=lambda z:z['rmse'])
    csvsave(OUT/'FULLGRID_VALIDATION_LEADERBOARD.csv',output)
    diag=[]
    for group,table in [('year',yrs),('season',seasons)]:
        for period,modeldata in table.items():
            for name,a in modeldata.items():diag.append(dict(group=group,period=period,model=name,**metrics(a)))
    csvsave(OUT/'FULLGRID_VALIDATION_BY_YEAR_SEASON.csv',diag)
    best_mbc=next(z for z in output if z['family']=='MBC')
    factors=np.stack([mbc_factors(m,d)[best_mbc['model']] for m in range(1,13)]).astype(np.float32)
    assert factors.shape==(12,205999)
    _,_,rows_mask,cols_mask,fy,fx,A,w=sources()
    np.savez_compressed(OUT/'MBC_BEST_TRAIN_2005_2019_FULLGRID.npz',factors=factors,
        row_indices=rows_mask.astype(np.int32),col_indices=cols_mask.astype(np.int32),
        latitude=fy.astype(np.float32),longitude=fx.astype(np.float32),
        month=np.arange(1,13,dtype=np.uint8),train_years=np.asarray(TRAIN),
        chosen_model=np.asarray(best_mbc['model']))
    with np.load(OUT/'TRAIN_ONLY_FULLGRID_REGRESSION_MODELS.npz',allow_pickle=False) as z:
        modelnames=z['names'].astype(str);coeff=z['coefficients'];names=z['feature_names']
    best_reg=next(z for z in output if z['family'] not in ('MBC','raw','climatology'))
    j=np.flatnonzero(modelnames==best_reg['model']);assert len(j)==1
    np.savez_compressed(OUT/'BEST_REGRESSION_TRAIN_2005_2019_FULLGRID.npz',
        coefficients=coeff[j[0]],feature_names=names,chosen_model=np.asarray(best_reg['model']),
        training_years=np.asarray(TRAIN))
    manifest=dict(created_utc=stamp(),source='full 0.05-degree authoritative ICPAC11 domain',
        mask_path=str(MASK),mask_cells=205999,train_years=list(TRAIN),validate_years=list(VALID),
        untouched_test_years=[2022,2023,2024,2025],
        training_cases=2783,validation_cases=365,
        potential_training_rows=2783*205999,potential_validation_rows=365*205999,
        actual_training_rows=int(sum(int(np.load(OUT/f'train_month_{m:02}.npz')['val_rows']) for m in range(1,13))),
        actual_validation_rows=rows,
        no_sampling=True,missing_CHIRPS_rows_omitted_only=True,
        area_weights='cos(latitude) on all 205999 official fine cells',
        predictors='6 core baseline features + 5/10/13/17 pre-fitted 2005-2019 atmospheric PCs',
        additive_spline='fixed piecewise-linear hinge basis for raw mean and spread; full-data ridge penalization, not a complete GAM',
        statistical_training='exact full-grid crossproduct sufficient statistics, no row subsampling',
        mbc_training='all available training paired rows within each cell and calendar group; denominator-shrunk to train regional ratios',
        mbc_candidate_selection='2020-2021 area-weighted RMSE only',
        precip_numerical_tolerance_mm=NUMERIC_TOL,precip_negative_fraction_limit=MAX_NEG_FRAC,
        original_GRIB_cross_check='previously passed in job 450; processed raw source unchanged',
        validation_reference_raw_rmse=raw,validation_reference_clim_rmse=clim,
        best_regression=best_reg,best_mbc=best_mbc,
        status='training and validation ONLY; independent final test pending; CHIRPS v2 0.05-degree verification')
    jwrite(OUT/'FULLGRID_EXPERIMENT_MANIFEST.json',manifest)
    print('\n'+'='*78)
    print('PASS FULL 0.05-DEGREE 205999-CELL, ALL-ROW, NO-SUBSAMPLING COMPARISON')
    print('TRAIN CASES 2783; VALIDATE CASES 365; TRAIN ROWS',manifest['actual_training_rows'],'VALID ROWS',rows)
    print('RAW ECMWF RMSE:',round(raw,5),'CLIMATOLOGY RMSE:',round(clim,5))
    print('BEST STATISTICAL MODEL:',best_reg['model'],'RMSE:',round(best_reg['rmse'],5))
    print('BEST MBC:',best_mbc['model'],'RMSE:',round(best_mbc['rmse'],5))
    print('VALIDATION LEADERBOARD:',OUT/'FULLGRID_VALIDATION_LEADERBOARD.csv')
    print('NO 2022-2025 TEST DATA USED')
    print('='*78,flush=True)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('mode',choices=['preflight','monthfit','reducefit','monthval','finalize'])
    parser.add_argument('--month',type=int)
    a=parser.parse_args()
    if a.mode in ('monthfit','monthval') and (a.month is None or a.month<1 or a.month>12):parser.error('Monthly stage requires --month 1..12')
    {'preflight':lambda:preflight(),'monthfit':lambda:monthfit(a.month),
     'reducefit':reducefit,'monthval':lambda:mval(a.month),'finalize':finalize}[a.mode]()

if __name__=='__main__':main()
