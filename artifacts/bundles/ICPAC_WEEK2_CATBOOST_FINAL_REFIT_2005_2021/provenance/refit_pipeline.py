#!/usr/bin/env python3
"""Final ICPAC Week-2 CatBoost refit. Development years: 2005–2021 only.

The original, audited source iterators are reused rather than approximating
ECMWF lead accumulation, CHIRPS masking or atmospheric interpolation.
Output paths are versioned; the historical training and test results stay intact.
"""
from __future__ import annotations
import argparse
import csv
import datetime as dt
import hashlib
import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path

# Avoid spawning BLAS threads in every Slurm worker before importing NumPy.
for key in ('OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ.setdefault(key,'1')
import numpy as np

ROOT=Path('/scratch/njoel/s2s_master_data/results/ICPAC_RETRAIN_2005_2025_V1')
CODE=Path('/scratch/njoel/code/s2s_unified_raw_20261018')
OUT=ROOT/'FINAL_REFIT_CATBOOST_2005_2021_V1'
SRC=CODE/'FULLGRID_STATS_MBC_20261022/fullgrid_stats_mbc.py'
# Reuse the exact historic PCA arithmetic. Prefer the original HPC script;
# ship a pristine copy as fallback because the old Slurm launcher put it at CODE root.
PCA_SRC=next((p for p in (
    CODE/'icpac_fit_pca_2005_2019.py',
    CODE/'PCA_TRAIN_2005_2019/icpac_fit_pca_2005_2019.py',
    Path(__file__).with_name('foundation_pca_source.py'),
) if p.is_file()), CODE/'icpac_fit_pca_2005_2019.py')
ML_SRC=CODE/'ML_FULLGRID_ALLROWS_STAGE1_20261022/prepare_fullgrid_ml.py'
MASK=Path('/scratch/njoel/ICPAC_DATA_HUB/DOMAIN/authoritative_icpac11_mask.npz')
ORIGINAL_MODEL=ROOT/'CATBOOST_VALIDATION_SELECTION_20261023/CatBoost_17PC_LOYO_RESIDUAL_FULLROWS.cbm'
OLD_POLICY=ROOT/'HYBRID_POLICY_SELECTION_20261023/HYBRID_POLICY_MANIFEST.json'
PCA_DIR=OUT/'pca'
MBC_DIR=OUT/'mbc'
FEATURE_DIR=OUT/'features'
TEXT_DIR=OUT/'tsv'
MODEL_DIR=OUT/'model'
BUNDLE_DIR=OUT/'deployment'
PCA_FILE=PCA_DIR/'ATMOS30_PCA_REFIT_2005_2021.npz'
MBC_FILE=MBC_DIR/'MBC_OPERATIONAL_MONTHLY_PRIOR500_CAP3_REFIT_2005_2021.npz'
FEATURE_MANIFEST=FEATURE_DIR/'FULL_REFIT_FEATURE_STORE_MANIFEST.json'
INPUT_LOCK=OUT/'REFIT_SCIENTIFIC_INPUT_LOCK.json'
TSV_FULL=TEXT_DIR/'CatBoost_REFIT_ALL_2005_2021.tsv'
TSV_META=TEXT_DIR/'FULL_TSV_MANIFEST.json'
CD=TEXT_DIR/'catboost_features.cd'
QUANT=MODEL_DIR/'CatBoost_REFIT_2005_2021.quantized'
QUANT_META=MODEL_DIR/'QUANTIZED_POOL_MANIFEST.json'
MODEL=MODEL_DIR/'CatBoost_MBC_LOYO_FINAL_REFIT_2005_2021.cbm'
MODEL_META=MODEL_DIR/'CATBOOST_FINAL_REFIT_MANIFEST.json'
YEARS=tuple(range(2005,2022))
N=205999
NC=26
CASE_EXPECT=3148
ROW_EXPECT=647228800
F=['X_mean_mmweek','X_spread_mmweek','latitude_deg','longitude_deg','doy_sin','doy_cos','MBC_forecast_mmweek']+[f'atmospheric_PC{i:02}' for i in range(1,18)]
PRIOR=500.0
FLOOR=0.2
CAP=3.0
MODEL_PARAMS=dict(iterations=300,depth=6,learning_rate=0.05,l2_leaf_reg=8,
                  loss_function='RMSE',random_seed=20261022,task_type='CPU',
                  bootstrap_type='No',boosting_type='Plain',used_ram_limit='80gb')


def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(16*1024*1024),b''): h.update(b)
    return h.hexdigest()


def load_module(path, name):
    if not path.is_file():raise FileNotFoundError(path)
    spec=importlib.util.spec_from_file_location(name,path)
    mod=importlib.util.module_from_spec(spec)
    sys.modules[name]=mod
    spec.loader.exec_module(mod)
    return mod


def original():
    m=load_module(SRC,'icpac_refit_original')
    # No edits to the canonical module on the filesystem.
    if m.TRAIN!=tuple(range(2005,2020)) or m.VALID!=(2020,2021):
        raise RuntimeError('Canonical temporal partitions have changed')
    if m.MASK!=MASK or m.FEATS!=atmospheric_features():
        raise RuntimeError('Canonical mask or atmospheric feature order changed')
    return m


def atmospheric_features():
    names=['q850','q700','u850','v850','wind850','qu850','qv850','qwind850',
           't850','t500','deltaT850_500','gh500','u200','v200','shear200_850']
    return [x+s for x in names for s in ('_mean','_spread')]


def cases(m,month):
    # The CCA inventory already excludes late inits whose target extends beyond
    # the 2019 / 2021 partition boundary. This excludes any 2022 overlap.
    selected=m.data_cases(month)
    assert all(2005<=y<=2021 for _,y in selected)
    assert len(selected)==len(set(selected))
    return selected


def write_json(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name('.'+path.name+'.tmp')
    if path.exists():raise FileExistsError(f'Write-once JSON exists: {path}')
    with temp.open('w') as f:
        json.dump(obj,f,indent=2,allow_nan=False)
        f.flush();os.fsync(f.fileno())
    os.replace(temp,path)


def saved(path,meta,required=None):
    if not path.exists() and not meta.exists():return False
    if not path.is_file() or not meta.is_file():
        raise RuntimeError(f'Incomplete output; inspect before retry: {path} {meta}')
    d=json.loads(meta.read_text())
    if d.get('sha256')!=sha(path):raise RuntimeError(f'Hash mismatch: {path}')
    if required:
        for k,v in required.items():
            if d.get(k)!=v:raise RuntimeError(f'Resume metadata mismatch {path} {k}')
    print('PASS already complete:',path,flush=True)
    return True


def atomic_npz(path, **values):
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():raise FileExistsError(path)
    tmp=path.with_name('.'+path.stem+'.tmp.npz')
    if tmp.exists():tmp.unlink()  # An abandoned incomplete temporary artifact.
    np.savez_compressed(tmp,**values)
    with np.load(tmp,allow_pickle=False) as z:
        assert z.files and all(np.asarray(z[k]).size>0 for k in z.files)
    os.replace(tmp,path)



def input_fingerprints():
    """Source-code and metadata seal; does not read holdout meteorology."""
    paths={'canonical_source':SRC,'pca_source':PCA_SRC,'feature_source':ML_SRC,
           'authoritative_mask':MASK,'historic_frozen_model':ORIGINAL_MODEL,
           'historic_validation_policy':OLD_POLICY}
    cca=ROOT/'CCA_DIAGNOSTIC_2005_2021'
    for month in range(1,13):
        paths[f'eligible_date_inventory_{month:02d}']=cca/f'cca_month_{month:02d}.npz'
    return {key:dict(path=str(path),sha256=sha(path)) for key,path in paths.items()}


def input_gate():
    if not INPUT_LOCK.is_file():
        raise RuntimeError('REFIT scientific preflight lock missing: do not run stages out of order')
    expected=json.loads(INPUT_LOCK.read_text())
    if expected.get('scientific_inputs')!=input_fingerprints():
        raise RuntimeError('A frozen scientific input changed during refit; stop and investigate')
    if expected.get('cases')!=CASE_EXPECT or expected.get('rows')!=ROW_EXPECT:
        raise RuntimeError('Refit input inventory changed')


def preflight():
    m=original()
    inventory=m.case_inventory()
    assert len(inventory)==CASE_EXPECT
    assert sum(y<=2019 for _,y in inventory)==2783
    assert sum(y>=2020 for _,y in inventory)==365
    assert all(str(np.datetime64(d)+np.timedelta64(13,'D'))<='2021-12-31' for d,_ in inventory)
    assert not set(range(2022,2026)).intersection(y for _,y in inventory)
    with np.load(MASK,allow_pickle=False) as z:
        assert z['domain_mask'].shape==(800,700) and int(z['domain_mask'].sum())==N
    for f in (PCA_SRC,ML_SRC,ORIGINAL_MODEL,OLD_POLICY):
        if not f.is_file():raise FileNotFoundError(f)
    d=json.loads(OLD_POLICY.read_text())
    if d['status']!='VALIDATION_POLICY_SELECTED_NOT_HOLDOUT_VERIFIED':
        raise RuntimeError('Frozen historical policy changed')
    if sha(ORIGINAL_MODEL)!=d['artifacts']['catboost_sha256']:
        raise RuntimeError('Old frozen CatBoost checksum differs')
    p=load_module(PCA_SRC,'icpac_old_pca')
    assert p.FEATS==m.FEATS and p.MASK==m.MASK
    _=p.ready()
    if not m.R.exists() or not m.CH.exists() or not m.PRESS.is_dir():
        raise FileNotFoundError('Original ECMWF/CHIRPS sources unavailable')
    free=shutil.disk_usage(OUT.parent).free
    if free<500*(2**30):raise RuntimeError('Require at least 500 GiB free scratch for full refit')
    OUT.mkdir(parents=True,exist_ok=True)
    lock=dict(scientific_inputs=input_fingerprints(),cases=CASE_EXPECT,rows=ROW_EXPECT,
              eligible_years=list(YEARS),test_years_forbidden=[2022,2023,2024,2025])
    if INPUT_LOCK.exists():
        if json.loads(INPUT_LOCK.read_text())!=lock:
            raise RuntimeError('Existing scientific source fingerprint differs; do not continue')
    else:write_json(INPUT_LOCK,lock)
    print(f'PASS preflight: {CASE_EXPECT} development cases / {ROW_EXPECT:,} records, '
          '205999 official grid cells, no 2022+ target or atmospheric field used',flush=True)
    print('Free scratch GiB:',round(free/2**30,1),flush=True)
    print('Canonical source hashes:',sha(SRC),sha(ML_SRC),sha(PCA_SRC),flush=True)


def pca_month(month):
    dst=PCA_DIR/f'month_{month:02d}_moments.npz'
    meta=PCA_DIR/f'month_{month:02d}_moments.json'
    if saved(dst,meta,{'month':month}):return
    src=original(); old=load_module(PCA_SRC,'icpac_refit_pca')
    schedule=cases(src,month)
    by_init={}
    for date,year in schedule:
        by_init.setdefault('2025'+date[5:7]+date[8:10],[]).append(year)
    files=old.monthly_paths(month)
    if len(files)!=len(by_init):raise RuntimeError('PCA pressure file inventory drift')
    lat,lon=old.load_geometry(files[0])
    G,b,weight,ncell=old.sparse_bilinear_gram(lat,lon)
    count=0; nweight=0.; mu=np.zeros(30);M2=np.zeros((30,30))
    for file in files:
        stamp=file.name.split('_mv')[1][:8]
        selected=by_init.get(stamp)
        if selected is None:raise RuntimeError(f'Unexpected pressure file: {file}')
        import xarray as xr
        with xr.open_dataset(file,decode_times=True) as ds:
            yrs=np.asarray(ds.time.dt.year.values).astype(int)
            hours=np.asarray(ds.step.values).astype('timedelta64[h]').astype(np.int64)
            lead=[int(np.flatnonzero(hours==h)[0]) for h in old.LEADS]
            lev={int(x):i for i,x in enumerate(ds.isobaricInhPa.values)}
            for year in selected:
                ind=np.flatnonzero(yrs==year)
                if len(ind)!=1:raise RuntimeError((file,year))
                X=old.atm_matrix(ds,int(ind[0]),lead,lev)
                if X.shape!=(648,30) or not np.isfinite(X).all():raise RuntimeError('Bad PCA atmosphere')
                average=(b@X)/weight
                centered=X-average
                local2=centered.T@(G@centered)
                if not count:
                    mu=average;M2=local2.copy();nweight=weight
                else:
                    new=nweight+weight;delta=average-mu
                    M2+=local2+np.outer(delta,delta)*nweight*weight/new
                    mu+=delta*weight/new;nweight=new
                count+=1
        print(f'PCA M{month:02d}: pressure init {stamp}; accumulated {count} cases',flush=True)
    assert count==len(schedule) and ncell==N
    atomic_npz(dst,weight_sum=np.float64(nweight),mean=mu,M2=(M2+M2.T)/2,
               cases=np.int64(count),month=np.int32(month),features=np.asarray(atmospheric_features()),
               years=np.asarray(YEARS),mask_cells=np.int32(N))
    write_json(meta,dict(sha256=sha(dst),month=month,cases=count,source='development eligible dates only'))
    print('PASS full-data PCA month',month,count,flush=True)


def pca_final():
    meta=PCA_DIR/'PCA_REFIT_MANIFEST.json'
    if saved(PCA_FILE,meta,{'cases':CASE_EXPECT}):return
    n=0.;mean=np.zeros(30);M2=np.zeros((30,30)); cases_total=0; hashes={}
    for m in range(1,13):
        path=PCA_DIR/f'month_{m:02d}_moments.npz'
        manifest=json.loads((PCA_DIR/f'month_{m:02d}_moments.json').read_text())
        if sha(path)!=manifest['sha256']:raise RuntimeError('PCA month altered')
        with np.load(path,allow_pickle=False) as z:
            assert list(z['features'])==atmospheric_features()
            a=float(z['weight_sum']);v=z['mean']; q=z['M2']; c=int(z['cases'])
        if n==0:n=a;mean=v.copy();M2=q.copy()
        else:
            new=n+a; delta=v-mean
            M2+=q+np.outer(delta,delta)*n*a/new
            mean+=delta*a/new;n=new
        cases_total+=c;hashes[path.name]=sha(path)
    assert cases_total==CASE_EXPECT,(cases_total,CASE_EXPECT)
    C=(M2+M2.T)/(2*n);var=np.diag(C)
    if not np.isfinite(var).all() or np.any(var<=0):raise RuntimeError('Bad PCA feature variances')
    scale=np.sqrt(var);R=C/scale[:,None]/scale[None,:];R=(R+R.T)/2
    values,vectors=np.linalg.eigh(R);sort=np.argsort(values)[::-1]
    vals=np.maximum(0,values[sort]);components=vectors[:,sort].T.copy()
    for v in components:
        if v[np.argmax(np.abs(v))]<0:v*=-1
    ratio=vals/vals.sum()
    assert components.shape==(30,30) and np.isfinite(components).all()
    atomic_npz(PCA_FILE,mean=mean,scale=scale,components=components,eigenvalues=vals,
               explained_variance_ratio=ratio,cumulative_explained_variance=np.cumsum(ratio),
               feature_names=np.asarray(atmospheric_features()),training_years=np.asarray(YEARS),
               train_cases=np.int32(cases_total),initializations=np.int32(186),
               cell_count=np.int32(N),area_weighted=np.array(True))
    write_json(meta,dict(sha256=sha(PCA_FILE),cases=cases_total,training_years=list(YEARS),
                         monthly_sha256=hashes,explained_variance_17=float(sum(ratio[:17])),
                         source_sha256=sha(PCA_SRC)))
    print('PASS refitted atmospheric 30→17 PCA, 2005–2021 development only',flush=True)


def mbc_month(month):
    dst=MBC_DIR/f'MBC_LOYO_MONTH_{month:02d}_REFIT_2005_2021.npz'
    meta=MBC_DIR/f'MBC_LOYO_MONTH_{month:02d}.json'
    if saved(dst,meta,{'month':month}):return
    src=original()
    sched=cases(src,month)
    Y=np.zeros((17,N),dtype=np.float64); X=np.zeros((17,N),dtype=np.float64)
    C=np.zeros((17,N),dtype=np.int32);year_cases=np.zeros(17,dtype=np.int32)
    rows=0;used=set()
    for part in ('train','valid'):
        for obs,raw,_x,w,date,year,*_ in src.month_iter(month,part,with_atmos=False):
            if (date,year) not in sched or (date,year) in used:
                raise RuntimeError(f'Unexpected or duplicate MBC training case {date}')
            used.add((date,year))
            good=np.isfinite(obs)&np.isfinite(raw)
            if np.count_nonzero(good)!=205600:raise RuntimeError(f'Target coverage drift: {date}')
            i=year-2005
            Y[i,good]+=obs[good];X[i,good]+=raw[good];C[i,good]+=1
            year_cases[i]+=1;rows+=int(good.sum())
    if len(used)!=len(sched) or rows!=len(sched)*205600:
        raise RuntimeError('MBC train + validation case inventory mismatch')
    w=np.asarray(w,dtype=np.float64)
    SUMY=Y.sum(axis=0);SUMX=X.sum(axis=0)
    if not np.all(SUMX>=0) or not np.isfinite(SUMY).all():raise RuntimeError('Bad MBC sums')
    def mbc_factor(y,x):
        ratio=float((w@y)/(w@x))
        if not np.isfinite(ratio) or ratio<=0:raise RuntimeError('MBC global ratio invalid')
        z=np.clip((y+PRIOR*ratio)/(x+PRIOR),FLOOR,CAP)
        if not np.isfinite(z).all():raise RuntimeError('MBC factors invalid')
        return z.astype(np.float32)
    loo=np.stack([mbc_factor(SUMY-Y[j],SUMX-X[j]) for j in range(17)])
    op=mbc_factor(SUMY,SUMX)
    assert loo.shape==(17,N) and op.shape==(N,)
    atomic_npz(dst,month=np.int32(month),years=np.asarray(YEARS),training_year_factor=loo,
               operational_factor=op,obs_sum=SUMY,raw_sum=SUMX,paired_n=C.sum(axis=0),
               year_case_count=year_cases,prior=np.float64(PRIOR),floor=np.float64(FLOOR),
               cap=np.float64(CAP),rows=np.int64(rows),cases=np.int32(len(sched)))
    write_json(meta,dict(sha256=sha(dst),month=month,rows=rows,cases=len(sched),
                         year_cases=year_cases.tolist(),training_years=list(YEARS),
                         no_own_year_mbc_targets=True))
    print(f'PASS OOF MBC month {month:02d}: {len(sched)} cases, {rows:,} rows',flush=True)


def mbc_final():
    meta=MBC_DIR/'MBC_REFIT_MANIFEST.json'
    if saved(MBC_FILE,meta,{'cases':CASE_EXPECT}):return
    src=original();_,_,rr,cc,lat,lon,_,w=src.sources()
    factors=[];rows=0;cases_total=0; month_hash={};clim=[]
    for m in range(1,13):
        p=MBC_DIR/f'MBC_LOYO_MONTH_{m:02d}_REFIT_2005_2021.npz'
        d=json.loads((MBC_DIR/f'MBC_LOYO_MONTH_{m:02d}.json').read_text())
        if sha(p)!=d['sha256']:raise RuntimeError('MBC LOYO file checksum mismatch')
        with np.load(p,allow_pickle=False) as z:
            factors.append(z['operational_factor'].copy());rows+=int(z['rows']);cases_total+=int(z['cases'])
            s=z['obs_sum'];n=z['paired_n'];v=np.full(N,np.nan)
            np.divide(s,n,out=v,where=n>0)
            regional=float((w@s)/(w@n))
            v[n<=0]=regional
            if not np.isfinite(v).all():raise RuntimeError('Invalid development climatology')
            clim.append(v.astype(np.float32))
        month_hash[p.name]=sha(p)
    assert rows==ROW_EXPECT and cases_total==CASE_EXPECT
    factors=np.stack(factors)
    assert factors.shape==(12,N)
    atomic_npz(MBC_FILE,factors=factors,months=np.arange(1,13),train_years=np.asarray(YEARS),
               row_indices=rr,col_indices=cc,latitude=lat,longitude=lon,
               chosen_model=np.asarray('MBC_monthly_prior500_cap3'),
               training_strategy=np.asarray('Development 2005-2021 full for inference; year-excluded factors for residual training'))
    cl=MBC_DIR/'TRAINING_CLIMATOLOGY_2005_2021.npz'
    if not cl.exists():atomic_npz(cl,mean_mmweek=np.stack(clim),training_years=np.asarray(YEARS),
                                  calendar_months=np.arange(1,13),official_mask_cells=np.int32(N))
    write_json(meta,dict(sha256=sha(MBC_FILE),cases=cases_total,rows=rows,months=list(range(1,13)),
                         month_sha256=month_hash,climatology_sha256=sha(cl),
                         no_test_data=True,leakage_rule='leave one calendar year out for ML residual targets'))
    print('PASS MBC factors and 2005–2021 mean climatology final',flush=True)


def feature_month(month):
    dest=FEATURE_DIR/f'refit_month_{month:02d}.f32'
    meta=FEATURE_DIR/f'refit_month_{month:02d}.json'
    if saved(dest,meta,{'month':month}):return
    src=original();ml=load_module(ML_SRC,'icpac_refit_feature')
    # Canonical PCA loader validates the new development-year list.
    src.PCA=PCA_FILE;src.TRAIN=YEARS
    if ml.FEATURES!=F:raise RuntimeError('24-feature schema changed')
    src.load_pca()
    with np.load(MBC_DIR/f'MBC_LOYO_MONTH_{month:02d}_REFIT_2005_2021.npz',allow_pickle=False) as z:
        oof=z['training_year_factor'].copy()
    expected=set(cases(src,month))
    seen=set();ranges=[];total=0;dig=hashlib.sha256()
    tmp=dest.with_name('.'+dest.name+'.tmp')
    if tmp.exists():tmp.unlink()
    dest.parent.mkdir(parents=True,exist_ok=True)
    try:
        with tmp.open('wb',buffering=16*1024*1024) as f:
            for part in ('train','valid'):
                for obs,raw,x,w,date,year,*_ in src.month_iter(month,part):
                    if (date,year) not in expected or (date,year) in seen:
                        raise RuntimeError(f'Unexpected/duplicate row case: {date}')
                    seen.add((date,year))
                    good=np.isfinite(obs)&np.isfinite(raw)
                    count=int(good.sum())
                    if count!=205600:raise RuntimeError(f'Unexpected CHIRPS missing cells at {date}: {count}')
                    allfeatures=ml.feature_build(raw,x,oof[year-2005])
                    a=np.empty((count,NC),dtype='<f4')
                    a[:,0]=obs[good];a[:,1]=w[good];a[:,2:]=allfeatures[good]
                    if not np.isfinite(a).all() or np.any(a[:,1]<=0):raise RuntimeError('Invalid training rows')
                    binary=a.tobytes();f.write(binary);dig.update(binary)
                    ranges.append(dict(date=date,year=year,offset=total,count=count))
                    total+=count
                    if len(ranges)%20==0:
                        print(f'FEATURE M{month:02d} {len(ranges)} cases, {total:,} rows',flush=True)
            f.flush();os.fsync(f.fileno())
        if seen!=expected or total!=len(expected)*205600 or tmp.stat().st_size!=total*NC*4:
            raise RuntimeError('Refit feature shard incomplete')
        os.replace(tmp,dest)
        write_json(meta,dict(month=month,rows=total,cases=len(ranges),sha256=dig.hexdigest(),
                             pca_sha256=sha(PCA_FILE),mbc_month_sha256=sha(MBC_DIR/f'MBC_LOYO_MONTH_{month:02d}_REFIT_2005_2021.npz'),
                             features=F,row_width=NC,case_ranges=ranges,columns=['truth','coslat']+F,
                             temporal_rule='2005-2021 development, year-excluded MBC per training case'))
    finally:
        if tmp.exists():tmp.unlink()
    print(f'PASS FEATURE M{month:02d} cases={len(ranges)} rows={total:,}',flush=True)


def feature_audit():
    already=FEATURE_MANIFEST.exists()
    rows=0;cases_total=0;items=[]
    for m in range(1,13):
        p=FEATURE_DIR/f'refit_month_{m:02d}.f32';meta=FEATURE_DIR/f'refit_month_{m:02d}.json'
        d=json.loads(meta.read_text())
        if d['month']!=m or d['row_width']!=NC or d['features']!=F or d['pca_sha256']!=sha(PCA_FILE):
            raise RuntimeError('Feature schema or PCA changed')
        if d['mbc_month_sha256']!=sha(MBC_DIR/f'MBC_LOYO_MONTH_{m:02d}_REFIT_2005_2021.npz'):
            raise RuntimeError('LOYO MBC changed')
        if p.stat().st_size!=d['rows']*NC*4 or sha(p)!=d['sha256']:
            raise RuntimeError('Refit feature payload changed')
        rows+=d['rows'];cases_total+=d['cases'];items.append(dict(month=m,cases=d['cases'],rows=d['rows'],sha256=d['sha256']))
    if (rows,cases_total)!=(ROW_EXPECT,CASE_EXPECT):raise RuntimeError((rows,cases_total))
    expected=dict(status='PASS',rows=rows,cases=cases_total,months=items,
                  pca_sha256=sha(PCA_FILE),mbc_sha256=sha(MBC_FILE),
                  no_subsampling=True,mask_cells=N,features=F,
                  test_period_not_used='2022-2025',source_code_sha256=sha(SRC))
    if already:
        found=json.loads(FEATURE_MANIFEST.read_text())
        if found!=expected:raise RuntimeError('Existing audited feature manifest changed')
    else:write_json(FEATURE_MANIFEST,expected)
    print(f'PASS FULL REFIT FEATURES {rows:,} rows / {cases_total} cases, no sampling',flush=True)


def tsv_month(month):
    path=TEXT_DIR/f'catboost_refit_month_{month:02d}.tsv'
    meta=TEXT_DIR/f'catboost_refit_month_{month:02d}.json'
    if saved(path,meta,{'month':month}):return
    if not FEATURE_MANIFEST.exists():raise RuntimeError('Features must pass audit first')
    d=json.loads((FEATURE_DIR/f'refit_month_{month:02d}.json').read_text())
    f=FEATURE_DIR/f'refit_month_{month:02d}.f32'
    if sha(f)!=d['sha256']:
        raise RuntimeError('Source feature shard checksum changed before TSV conversion')
    n=d['rows'];a=np.memmap(f,dtype='<f4',mode='r',shape=(n,NC))
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name('.'+path.name+'.tmp')
    if temp.exists():temp.unlink()
    try:
        with temp.open('w',buffering=16*1024*1024) as dst:
            for i in range(0,n,50000):
                b=np.asarray(a[i:i+50000]);o=np.empty_like(b)
                o[:,0]=b[:,0]-b[:,8]  # Residual relative to year-excluded MBC.
                o[:,1:]=b[:,1:]
                np.savetxt(dst,o,fmt='%.7g',delimiter='\t')
                if (i//50000)%100==0:print(f'TSV M{month:02d}: {i:,}/{n:,}',flush=True)
            dst.flush();os.fsync(dst.fileno())
        if temp.stat().st_size<=n*60:raise RuntimeError('TSV suspiciously small')
        os.replace(temp,path)
        write_json(meta,dict(month=month,rows=n,sha256=sha(path),source_sha256=sha(f),
                             float_encoding='%.7g',target='CHIRPS minus LOYO MBC',
                             feature_columns=24))
    finally:
        if temp.exists():temp.unlink()
    print('PASS TSV month',month,n,flush=True)


def tsv_merge():
    if saved(TSV_FULL,TSV_META,{'rows':ROW_EXPECT}):return
    TEXT_DIR.mkdir(parents=True,exist_ok=True)
    CD.write_text('0\tLabel\n1\tWeight\n')
    temp=TSV_FULL.with_name('.'+TSV_FULL.name+'.tmp')
    if temp.exists():temp.unlink()
    total=0;parts=[]
    try:
        with temp.open('wb',buffering=16*1024*1024) as dest:
            for m in range(1,13):
                file=TEXT_DIR/f'catboost_refit_month_{m:02d}.tsv'
                d=json.loads((TEXT_DIR/f'catboost_refit_month_{m:02d}.json').read_text())
                if sha(file)!=d['sha256']:raise RuntimeError('TSV shard changed')
                with file.open('rb',buffering=16*1024*1024) as inp:
                    shutil.copyfileobj(inp,dest,length=16*1024*1024)
                total+=int(d['rows']);parts.append(dict(month=m,sha256=d['sha256'],rows=d['rows']))
                print(f'MERGED {m}/12, total records={total:,}',flush=True)
            dest.flush();os.fsync(dest.fileno())
        if total!=ROW_EXPECT:raise RuntimeError('Merged TSV row mismatch')
        os.replace(temp,TSV_FULL)
        write_json(TSV_META,dict(sha256=sha(TSV_FULL),rows=total,parts=parts,
                                 column_description_sha256=sha(CD),
                                 full_row_training=True,source_feature_sha256=sha(FEATURE_MANIFEST)))
    finally:
        if temp.exists():temp.unlink()
    print('PASS full CatBoost training TSV:',total,'rows',flush=True)


def quantize():
    if saved(QUANT,QUANT_META,{'rows':ROW_EXPECT}):return
    if not TSV_META.exists() or not TSV_FULL.is_file():raise RuntimeError('Missing fully audited TSV')
    d=json.loads(TSV_META.read_text())
    if d['sha256']!=sha(TSV_FULL):raise RuntimeError('Full TSV changed')
    MODEL_DIR.mkdir(parents=True,exist_ok=True)
    from catboost.utils import quantize as cb_quantize
    from catboost import __version__ as version
    threads=int(os.environ.get('SLURM_CPUS_PER_TASK','16'))
    pool=cb_quantize(data_path=str(TSV_FULL),column_description=str(CD),
                     border_count=63,used_ram_limit='80gb',thread_count=threads,
                     random_seed=20261022)
    if pool.num_row()!=ROW_EXPECT or pool.num_col()!=24:
        raise RuntimeError('Quantized row or feature count wrong')
    tmp=QUANT.with_name('.'+QUANT.name+'.tmp')
    if tmp.exists():tmp.unlink()
    pool.save(str(tmp))
    os.replace(tmp,QUANT)
    write_json(QUANT_META,dict(sha256=sha(QUANT),rows=ROW_EXPECT,features=24,
                               tsv_sha256=sha(TSV_FULL),catboost_version=version,
                               quantization_border_count=63,random_seed=20261022))
    print('PASS quantized complete model pool',QUANT,flush=True)


def fit():
    if saved(MODEL,MODEL_META,{'rows':ROW_EXPECT}):return
    if not QUANT_META.is_file():raise RuntimeError('Quantized dataset not ready')
    d=json.loads(QUANT_META.read_text())
    if d['sha256']!=sha(QUANT):raise RuntimeError('Quantized pool checksum mismatch')
    from catboost import Pool,CatBoostRegressor,__version__ as version
    p=Pool('quantized://'+str(QUANT),thread_count=int(os.environ.get('SLURM_CPUS_PER_TASK','16')))
    if p.num_row()!=ROW_EXPECT or p.num_col()!=24:raise RuntimeError('Refit pool incomplete')
    parms=MODEL_PARAMS|dict(thread_count=int(os.environ.get('SLURM_CPUS_PER_TASK','16')),
                            allow_writing_files=True,train_dir=str(MODEL_DIR/'catboost_training_logs'),
                            verbose=25)
    model=CatBoostRegressor(**parms)
    snapshot=MODEL_DIR/'refit_training_progress.cbsnapshot'
    model.fit(p,save_snapshot=True,snapshot_file=str(snapshot),snapshot_interval=900)
    if model.tree_count_!=300:raise RuntimeError(f'Incorrect tree count: {model.tree_count_}')
    tmp=MODEL.with_name('.'+MODEL.name+'.tmp.cbm')
    if tmp.exists():tmp.unlink()
    model.save_model(str(tmp))
    from catboost import CatBoostRegressor as Check
    reload=Check();reload.load_model(str(tmp))
    if reload.tree_count_!=300 or len(reload.feature_names_)!=24:
        raise RuntimeError('Saved model not usable')
    os.replace(tmp,MODEL)
    write_json(MODEL_META,dict(sha256=sha(MODEL),rows=ROW_EXPECT,cases=CASE_EXPECT,trees=300,
                               training_years=list(YEARS),features=F,parameters=MODEL_PARAMS,
                               pca_sha256=sha(PCA_FILE),mbc_sha256=sha(MBC_FILE),
                               quantized_pool_sha256=sha(QUANT),catboost_version=version,
                               full_row_fit=True,no_validation_or_test_reserved_for_refit=True,
                               original_validation_refit_caveat='2020-2021 used for fitting, no longer an independent validation period',
                               historic_holdout_caveat='2022-2024 previously used to compare deployable policies; do not claim fresh independent score for new refit'))
    print('PASS final refitted CatBoost model',MODEL,'sha256=',sha(MODEL),flush=True)


def status():
    for name,path in [('PCA',PCA_FILE),('MBC',MBC_FILE),('feature audit',FEATURE_MANIFEST),
                      ('TSV',TSV_FULL),('quantized',QUANT),('model',MODEL)]:
        print(f'{name:15} {"READY" if path.is_file() else "MISSING"} {path}',flush=True)


def selftest():
    # Check the arithmetic of year-exclusion, row formatting and feature offsets.
    y=np.array([2.,4.,6.]);x=np.array([1.,2.,3.]);y_other=y.sum()-y[1]
    y[1]=1.e10
    assert abs((y.sum()-y[1])-y_other)<1e-4
    a=np.zeros((2,NC),dtype=np.float32);a[:,0]=[10,12];a[:,8]=[3,4]
    assert np.allclose(a[:,0]-a[:,8],[7,8])
    assert ROW_EXPECT==3148*205600 and len(F)==24 and NC==26
    print('PASS synthetic year-exclusion and residual column mapping',flush=True)


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('mode',choices=['selftest','preflight','pca-month','pca-final','mbc-month','mbc-final',
                                    'feature-month','feature-audit','tsv-month','tsv-merge','quantize','fit','status'])
    ap.add_argument('--month',type=int,default=0)
    a=ap.parse_args()
    actions={'selftest':selftest,'preflight':preflight,'pca-final':pca_final,
             'mbc-final':mbc_final,'feature-audit':feature_audit,'tsv-merge':tsv_merge,
             'quantize':quantize,'fit':fit,'status':status}
    if a.mode not in ('selftest','status','preflight'):input_gate()
    if a.mode in actions:actions[a.mode]()
    else:
        if not 1<=a.month<=12:raise ValueError('Specify --month 1..12')
        {'pca-month':pca_month,'mbc-month':mbc_month,'feature-month':feature_month,
         'tsv-month':tsv_month}[a.mode](a.month)

if __name__=='__main__':main()
