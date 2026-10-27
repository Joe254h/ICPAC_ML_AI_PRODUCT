#!/usr/bin/env python3
"""ICPAC-11 Hybrid7 + 17 train-fitted PCs: full-row disk-backed preparation.

2005-2019 train: LOYO MBC by year. 2020-2021 validation: 2005-2019 MBC.
Keeps every CHIRPS-valid 0.05-degree case-cell row; 2022+ is unread.
Each monthly binary shard has float32 columns [target, coslatitude, Hybrid7, PC1..PC17].
No row sampling, spatial coarsening, random shuffling, or data-induced subsampling.
"""
import os
for n in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
    os.environ.setdefault(n,'2')
import argparse, importlib.util, hashlib, json, sys, shutil, platform
from pathlib import Path
from datetime import datetime, timezone
import numpy as np

CODE=Path('/scratch/njoel/code/s2s_unified_raw_20261018/FULLGRID_STATS_MBC_20261022/fullgrid_stats_mbc.py')
ROOT=Path('/scratch/njoel/s2s_master_data/results/ICPAC_RETRAIN_2005_2025_V1')
STATS=ROOT/'FULLGRID_005_STATS_MBC_2005_2021'
LOYO=ROOT/'ML_HYBRID7_PCS_LOYO_2005_2021'
OUT=ROOT/'ML_HYBRID7_PCS_FULLROWS_V1'
FEATURES=['X_mean_mmweek','X_spread_mmweek','latitude_deg','longitude_deg','doy_sin','doy_cos','MBC_forecast_mmweek']+[f'atmospheric_PC{i:02}' for i in range(1,18)]
NC=26
EXPECTED={'train':572184800,'valid':75044000}


def load_source():
    assert CODE.exists(),CODE
    spec=importlib.util.spec_from_file_location('icpac_fullgrid_original',CODE)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    assert m.OUT==STATS and m.NBASE==23 and m.NBASIS==32
    assert m.TRAIN==tuple(range(2005,2020)) and m.VALID==(2020,2021)
    return m


def jsonwrite(path,data):
    tmp=path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(data,indent=2,allow_nan=False))
    os.replace(tmp,path)


def factor(m):
    path=LOYO/f'MBC_LOYO_MONTH_{m:02d}_TRAIN_2005_2019.npz'
    with np.load(path,allow_pickle=False) as z:
        a=z['training_year_factor'].astype(np.float32)
        b=z['validation_2020_2021_factor'].astype(np.float32)
        assert int(z['month'])==m and int(z['official_mask_cells'])==205999
        assert a.shape==(15,205999) and b.shape==(205999,)
        assert np.isfinite(a).all() and np.isfinite(b).all()
        return a,b


def feature_build(raw,x,mbc_factor):
    # Existing canonical x columns are normalized for the regression experiment:
    # raw/50, spread/20, lat/20, lon/50, sin, cos, PC1../4.
    assert x.shape==(205999,32) and raw.shape==(205999,)
    assert mbc_factor.shape==(205999,)
    f=np.empty((205999,24),dtype=np.float32)
    f[:,0]=raw
    f[:,1]=(x[:,1]*20).astype(np.float32)
    f[:,2]=(x[:,2]*20).astype(np.float32)
    f[:,3]=(x[:,3]*50).astype(np.float32)
    f[:,4]=x[:,4].astype(np.float32)
    f[:,5]=x[:,5].astype(np.float32)
    f[:,6]=raw*mbc_factor
    f[:,7:24]=(x[:,6:23]*4).astype(np.float32)
    np.testing.assert_allclose(f[:,0],x[:,0]*50,rtol=2e-6,atol=1e-4)
    assert np.isfinite(f).all() and (f[:,0]>=0).all() and (f[:,6]>=0).all()
    return f


def preflight():
    src=load_source();src.case_inventory();src.load_pca()
    OUT.mkdir(parents=True,exist_ok=True)
    manifest=json.loads((LOYO/'MBC_LOYO_ML_READINESS_MANIFEST.json').read_text())
    assert manifest['full_training_valid_rows']==EXPECTED['train']
    assert manifest['validation_rows']==EXPECTED['valid']
    assert manifest['full_mask_cells']==205999
    assert manifest['independent_test_years_not_accessed']==[2022,2023,2024,2025]
    s=json.loads((STATS/'FULLGRID_EXPERIMENT_MANIFEST.json').read_text())
    assert s['actual_training_rows']==EXPECTED['train'] and s['actual_validation_rows']==EXPECTED['valid']
    for month in range(1,13):factor(month)
    free=shutil.disk_usage(OUT).free
    needed=int((EXPECTED['train']+EXPECTED['valid'])*NC*4*1.10)
    print('Mask cells=205999; TRAIN cases=2783; VALID cases=365')
    print(f'Expect train rows={EXPECTED["train"]:,}, valid rows={EXPECTED["valid"]:,}')
    print(f'Estimated raw feature bytes={(EXPECTED["train"]+EXPECTED["valid"])*NC*4/2**30:.2f} GiB')
    print(f'Filesystem free={free/2**30:.2f} GiB; safety requirement={needed/2**30:.2f} GiB')
    assert free>=needed,('Insufficient shared scratch capacity; do not write large shards',free,needed)
    print('PASS: All existing source artifacts and storage preflight. NO 2022-2025 DATA USED.')


def shard(month,partition):
    assert partition in EXPECTED and 1<=month<=12
    src=load_source();OUT.mkdir(parents=True,exist_ok=True)
    a,b=factor(month)
    fp=OUT/f'{partition}_month_{month:02d}.f32'
    meta=OUT/f'{partition}_month_{month:02d}.json'
    if fp.exists() or meta.exists():
        raise FileExistsError(f'Refusing to overwrite existing shard: {fp} / {meta}')
    tmp=OUT/f'.{partition}_month_{month:02d}.f32.tmp'
    ref=STATS/f'train_month_{month:02d}.npz' if partition=='train' else STATS/f'validation_month_{month:02d}.json'
    if partition=='train':
        with np.load(ref,allow_pickle=False) as z:
            expected_cases=int(z['ncases']);expected_rows=int(z['val_rows'])
    else:
        v=json.loads(ref.read_text());expected_cases=int(v['cases']);expected_rows=int(v['valid_rows'])
    count=rows=0;digest=hashlib.sha256();cases=[]
    try:
        with tmp.open('wb',buffering=16*1024*1024) as fout:
            for obs,raw,x,w,date,year,_,_ in src.month_iter(month,partition):
                assert (2005<=year<=2019 if partition=='train' else 2020<=year<=2021)
                assert date[:4]==str(year) and date[5:7]==f'{month:02d}'
                good=np.isfinite(obs)&np.isfinite(raw)
                n=int(np.count_nonzero(good))
                assert n>0.95*205999,(date,n)
                mbc=a[year-2005] if partition=='train' else b
                full=feature_build(raw,x,mbc)
                r=np.empty((n,NC),dtype=np.float32)
                r[:,0]=obs[good]
                r[:,1]=w[good]
                r[:,2:]=full[good]
                assert np.isfinite(r).all() and (r[:,0]>=0).all() and (r[:,1]>0).all()
                bb=r.tobytes(order='C');fout.write(bb);digest.update(bb)
                cases.append(dict(date=date,year=year,offset=rows,count=n))
                rows+=n;count+=1
                if count%20==0:print(f'{partition} MONTH {month:02d}: cases={count} rows={rows:,}',flush=True)
            fout.flush();os.fsync(fout.fileno())
        assert count==expected_cases and rows==expected_rows,(month,partition,count,rows,expected_cases,expected_rows)
        assert tmp.stat().st_size==rows*NC*4
        os.replace(tmp,fp)
        data=dict(month=month,split=partition,rows=rows,cases=count,official_mask_cells=205999,
            row_width=NC,feature_names=FEATURES,fields=['target_mmweek','area_weight_coslat']+FEATURES,
            dtype='float32',sha256=digest.hexdigest(),case_ranges=cases,
            temporal_rule='Train 2005-2019, validate 2020-2021; test 2022-2025 untouched',
            mbc_training_rule='leave out target year' if partition=='train' else 'all 2005-2019')
        jsonwrite(meta,data)
        print(f'PASS {partition} MONTH {month:02d}: {count} forecast cases, {rows:,} valid cell-rows, {fp.stat().st_size/2**30:.3f} GiB',flush=True)
    finally:
        if tmp.exists():tmp.unlink()


def audit():
    case_sum={'train':0,'valid':0};row_sum={'train':0,'valid':0};report=[]
    for partition in EXPECTED:
        for month in range(1,13):
            fp=OUT/f'{partition}_month_{month:02d}.f32';meta=OUT/f'{partition}_month_{month:02d}.json'
            assert fp.exists() and meta.exists(),(partition,month)
            d=json.loads(meta.read_text())
            assert d['feature_names']==FEATURES and d['row_width']==NC
            assert d['month']==month and d['split']==partition
            assert fp.stat().st_size==int(d['rows'])*NC*4
            assert sum(c['count'] for c in d['case_ranges'])==d['rows']
            assert len(d['case_ranges'])==d['cases']
            assert d['case_ranges'][0]['offset']==0
            assert d['case_ranges'][-1]['offset']+d['case_ranges'][-1]['count']==d['rows']
            case_sum[partition]+=d['cases'];row_sum[partition]+=d['rows']
            report.append(dict(split=partition,month=month,cases=d['cases'],rows=d['rows'],bytes=fp.stat().st_size,sha256=d['sha256']))
    assert case_sum=={'train':2783,'valid':365},case_sum
    assert row_sum==EXPECTED,row_sum
    jsonwrite(OUT/'FULLGRID_ML_FEATURE_STORE_MANIFEST.json',dict(
        ready=True,created_utc=datetime.now(timezone.utc).isoformat(),
        train_cases=2783,validation_cases=365,rows=row_sum,feature_names=FEATURES,
        training_has_no_sampling=True,verification_resolution='0.05 degree',
        mask_cells=205999,CHIRPS_missing_targets_excluded_only=True,
        source_fullgrid=str(STATS),source_mbc_loyo=str(LOYO),
        leakage_safe_training_MBC='leave out own calendar year',
        validation_MBC='2005-2019 factors',test_years_never_accessed=[2022,2023,2024,2025],
        shards=report))
    print('PASS: 24 binary shards verified (12 months x TRAIN+VALIDATION)')
    print(f'PASS: TRAIN {case_sum["train"]} cases and {row_sum["train"]:,} rows (ALL)')
    print(f'PASS: VALID {case_sum["valid"]} cases and {row_sum["valid"]:,} rows (ALL)')
    print('PASS: 205999 official 0.05-degree cells, 24 Hybrid7+PC17 inputs, no sampling, test UNREAD')
    print(f'FEATURE STORE: {OUT}',flush=True)


def selftest():
    n=205999
    raw=np.linspace(0,90,n,dtype=np.float32)
    x=np.zeros((n,32),dtype=np.float64)
    x[:,0]=raw/50;x[:,1]=1.25;x[:,2]=0.2;x[:,3]=0.7
    x[:,4]=0.9;x[:,5]=0.1;x[:,6:23]=np.arange(17)/4.
    factors=np.full(n,0.8,dtype=np.float32)
    f=feature_build(raw,x,factors)
    assert f.shape==(n,24)
    np.testing.assert_allclose(f[:,6],raw*.8,rtol=1e-6,atol=1e-5)
    np.testing.assert_allclose(f[0,7:],np.arange(17),rtol=0,atol=1e-12)
    np.testing.assert_allclose(f[-1,7:],np.arange(17),rtol=0,atol=1e-12)
    print('PASS synthetic Hybrid7+PC17 feature shape/order/normalizations')

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('mode',choices=['selftest','preflight','month','audit']);ap.add_argument('--month',type=int);ap.add_argument('--split',choices=['train','valid'])
    args=ap.parse_args()
    if args.mode=='selftest':selftest()
    elif args.mode=='preflight':preflight()
    elif args.mode=='audit':audit()
    else:
        assert args.month and args.split
        shard(args.month,args.split)
