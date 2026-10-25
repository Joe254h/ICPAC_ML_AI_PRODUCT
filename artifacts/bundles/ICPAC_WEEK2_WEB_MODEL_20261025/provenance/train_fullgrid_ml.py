#!/usr/bin/env python3
"""Full-row, no-bagging 17-PC Hybrid7 residual LightGBM / CatBoost screening.

Prepare binary feature shards with prepare_fullgrid_ml.py before fitting.
This is a resource-heavy GLOBAL model; never truncate train rows if resources low.
Use saved models to evaluate all 75,044,000 matched validation cell-rows.
"""
import os
for name in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'):
    os.environ.setdefault(name,'12')
import argparse, bisect, csv, gc, json, shutil, sys
from pathlib import Path
from datetime import datetime, timezone
import numpy as np
from prepare_fullgrid_ml import OUT,NC,FEATURES,EXPECTED,jsonwrite
try:
    import lightgbm as _lgb_optional
    _SequenceBase=_lgb_optional.Sequence
except ImportError:
    _SequenceBase=object
MODEL_DIR=OUT/'models'


def records(part):
    assert part in EXPECTED
    specs=[];start=0
    for m in range(1,13):
        f=OUT/f'{part}_month_{m:02d}.f32'
        meta=json.loads((OUT/f'{part}_month_{m:02d}.json').read_text())
        n=int(meta['rows'])
        assert n*NC*4==f.stat().st_size
        specs.append((f,n,start,meta))
        start+=n
    assert start==EXPECTED[part]
    return specs


class FeatureSequence(_SequenceBase):
    # Compatible with lightgbm.Sequence duck-typed methods + batch_size.
    batch_size=65536
    def __init__(self,part):
        self.specs=records(part)
        self.mmaps=[np.memmap(p,dtype=np.float32,mode='r',shape=(n,NC)) for p,n,_,_ in self.specs]
        self.starts=[s for _,_,s,_ in self.specs]
        self.len=sum(n for _,n,_,_ in self.specs)
    def __len__(self):return self.len
    def __getitem__(self,index):
        if isinstance(index,(int,np.integer)):
            index=int(index)
            if index<0:index+=self.len
            if not 0<=index<self.len:raise IndexError(index)
            j=bisect.bisect_right(self.starts,index)-1
            return np.asarray(self.mmaps[j][index-self.starts[j],2:],dtype=np.float64)
        if isinstance(index,slice):
            a,b,step=index.indices(self.len)
            if step!=1:return self[list(range(a,b,step))]
            out=np.empty((b-a,24),dtype=np.float64);pos=0
            while a<b:
                j=bisect.bisect_right(self.starts,a)-1
                local=a-self.starts[j]
                take=min(b-a,self.mmaps[j].shape[0]-local)
                assert take>0
                out[pos:pos+take]=self.mmaps[j][local:local+take,2:]
                a+=take;pos+=take
            return out
        if isinstance(index,(list,np.ndarray)):
            idx=np.asarray(index,dtype=np.int64)
            out=np.empty((len(idx),24),dtype=np.float64)
            which=np.searchsorted(np.asarray(self.starts),idx,side='right')-1
            for j in np.unique(which):
                sel=which==j
                out[sel]=self.mmaps[j][idx[sel]-self.starts[j],2:]
            return out
        raise TypeError(type(index))


def ensure_full():
    f=OUT/'FULLGRID_ML_FEATURE_STORE_MANIFEST.json'
    if not f.is_file():raise RuntimeError('RUN FEATURE AUDIT FIRST; WILL NOT FIT A PARTIAL DATASET')
    d=json.loads(f.read_text()); assert d['ready'] and d['rows']==EXPECTED
    assert d['feature_names']==FEATURES and len(FEATURES)==24
    return d


def pack_targets(part):
    """Build contiguous disk-backed targets/area weights; no in-memory concatenation."""
    ensure_full();MODEL_DIR.mkdir(parents=True,exist_ok=True)
    yp=MODEL_DIR/f'{part}_target.f32';wp=MODEL_DIR/f'{part}_weight.f32'
    n=EXPECTED[part]
    if yp.exists() or wp.exists():
        assert yp.exists() and wp.exists() and yp.stat().st_size==4*n and wp.stat().st_size==4*n
        return yp,wp
    free=shutil.disk_usage(MODEL_DIR).free
    assert free>8*n+10*2**30,('Insufficient remaining disk for contiguous label/weight arrays',free)
    yy=np.memmap(str(yp)+'.tmp',mode='w+',dtype=np.float32,shape=(n,))
    ww=np.memmap(str(wp)+'.tmp',mode='w+',dtype=np.float32,shape=(n,))
    try:
        for f,nsh,offset,_ in records(part):
            a=np.memmap(f,dtype=np.float32,mode='r',shape=(nsh,NC))
            for start in range(0,nsh,100000):
                stop=min(start+100000,nsh)
                yy[offset+start:offset+stop]=a[start:stop,0]-a[start:stop,8]
                ww[offset+start:offset+stop]=a[start:stop,1]
        yy.flush();ww.flush()
        os.replace(str(yp)+'.tmp',yp);os.replace(str(wp)+'.tmp',wp)
    finally:
        del yy,ww
    print(f'PASS packed all {n:,} {part} targets+weights on disk',flush=True)
    return yp,wp


def lightgbm_train():
    ensure_full()
    try:import lightgbm as lgb
    except ImportError as e:raise RuntimeError('HPC conda env requires lightgbm') from e
    print('LightGBM version',lgb.__version__,flush=True)
    yp,wp=pack_targets('train')
    targets=np.memmap(yp,dtype=np.float32,mode='r',shape=(EXPECTED['train'],))
    weights=np.memmap(wp,dtype=np.float32,mode='r',shape=(EXPECTED['train'],))
    assert len(targets)==572184800
    seq=FeatureSequence('train')
    # LightGBM samples feature values when estimating bin thresholds internally.
    # Every row is nevertheless loaded into the constructed dataset for fitting.
    construct=dict(max_bin=63,min_data_in_bin=50,bin_construct_sample_cnt=200000,
        feature_pre_filter=False,num_threads=int(os.environ.get('SLURM_CPUS_PER_TASK',8)))
    dset=lgb.Dataset(seq,label=targets,weight=weights,feature_name=FEATURES,params=construct,free_raw_data=True)
    dset.construct()
    assert dset.num_data()==572184800 and dset.num_feature()==24
    print('PASS LightGBM full constructed rows',dset.num_data(),flush=True)
    config=dict(objective='regression',metric='rmse',learning_rate=0.05,
        num_leaves=31,max_depth=-1,min_data_in_leaf=5000,max_bin=63,
        lambda_l2=10.,feature_fraction=1.0,bagging_fraction=1.0,bagging_freq=0,
        verbosity=1,num_threads=int(os.environ.get('SLURM_CPUS_PER_TASK',8)),force_col_wise=True,
        data_sample_strategy='bagging')
    model=lgb.train(config,dset,num_boost_round=300)
    MODEL_DIR.mkdir(parents=True,exist_ok=True)
    outfile=MODEL_DIR/'LightGBM_17PC_LOYO_RESIDUAL_FULLROWS.txt'
    model.save_model(str(outfile))
    jsonwrite(MODEL_DIR/'LightGBM_17PC_TRAIN_MANIFEST.json',dict(
        trained_rows=int(dset.num_data()),features=FEATURES,
        target='CHIRPS_week2_minus_LOYO_MBC_week2',validation_years_not_fitted=[2020,2021],
        test_years_unread=[2022,2023,2024,2025],training_sampling_fraction=1.0,
        feature_bin_threshold_selection='internal LightGBM bin construction; not training-row subsampling',
        params=config,trees=300,model_path=str(outfile),timestamp_utc=datetime.now(timezone.utc).isoformat()))
    print('PASS LightGBM model fitted on ALL 572,184,800 training rows:',outfile,flush=True)


def catboost_train():
    ensure_full()
    from catboost import CatBoostRegressor
    from catboost.utils import quantize
    # CatBoost has a disk-file quantization path, but conversion to a full
    # text pool needs additional scratch. Never silently sample a smaller pool.
    MODEL_DIR.mkdir(parents=True,exist_ok=True)
    free=shutil.disk_usage(MODEL_DIR).free
    requirement=220*2**30
    assert free>=requirement,(f'CatBoost full-row TSV+quantization needs >=220 GiB free scratch',free/2**30)
    data_file=MODEL_DIR/'CatBoost_17PC_ALLROWS.tsv'
    cd=MODEL_DIR/'catboost_features.cd'
    cd.write_text('0\tLabel\n1\tWeight\n')
    if data_file.exists():raise FileExistsError(f'Refusing to append/truncate existing pool {data_file}')
    count=0
    print('Building CatBoost disk-backed pool from all unmodified verified training rows',flush=True)
    with data_file.open('w',buffering=16*1024*1024) as f:
        for fp,n,_,_ in records('train'):
            a=np.memmap(fp,dtype=np.float32,mode='r',shape=(n,NC))
            for k in range(0,n,50000):
                b=a[k:min(k+50000,n)]
                out=np.empty_like(b);out[:,0]=b[:,0]-b[:,8]
                out[:,1:]=b[:,1:]
                np.savetxt(f,out,fmt='%.7g',delimiter='\t')
                count+=len(b)
                if count%20000000<50000:print(f'CATBOOST TSV {count:,} rows',flush=True)
    assert count==EXPECTED['train'],count
    print('Quantizing CatBoost all-row pool',flush=True)
    pool=quantize(data_path=str(data_file),column_description=str(cd),
        border_count=63,used_ram_limit='80gb',thread_count=int(os.environ.get('SLURM_CPUS_PER_TASK',8)),
        random_seed=20261022)
    assert pool.num_row()==572184800 and pool.num_col()==24
    # Remove giant intermediate text only after successful quantization.
    data_file.unlink()
    qfile=MODEL_DIR/'CatBoost_17PC_ALLROWS.quantized'
    pool.save(str(qfile))
    model=CatBoostRegressor(iterations=300,depth=6,learning_rate=0.05,l2_leaf_reg=8,
        loss_function='RMSE',random_seed=20261022,task_type='CPU',thread_count=int(os.environ.get('SLURM_CPUS_PER_TASK',8)),
        bootstrap_type='No',boosting_type='Plain',used_ram_limit='80gb',verbose=25,
        allow_writing_files=False)
    model.fit(pool)
    dest=MODEL_DIR/'CatBoost_17PC_LOYO_RESIDUAL_FULLROWS.cbm'
    model.save_model(str(dest))
    jsonwrite(MODEL_DIR/'CatBoost_17PC_TRAIN_MANIFEST.json',dict(
        trained_rows=pool.num_row(),features=FEATURES,trees=300,
        target='CHIRPS_week2_minus_LOYO_MBC_week2',
        training_sampling_fraction=1.0,test_years_unread=[2022,2023,2024,2025],
        model_path=str(dest),quantized_data=str(qfile),
        timestamp_utc=datetime.now(timezone.utc).isoformat()))
    print('PASS CatBoost model trained on all 572,184,800 rows',dest,flush=True)


def score(model_kind):
    ensure_full()
    if model_kind=='lightgbm':
        import lightgbm as lgb
        model=lgb.Booster(model_file=str(MODEL_DIR/'LightGBM_17PC_LOYO_RESIDUAL_FULLROWS.txt'))
    else:
        from catboost import CatBoostRegressor
        model=CatBoostRegressor()
        model.load_model(str(MODEL_DIR/'CatBoost_17PC_LOYO_RESIDUAL_FULLROWS.cbm'))
    # Values are area-weighted; all 75,044,000 CHIRPS-valid rows accounted for.
    totals={k:np.zeros(10,dtype=np.float64) for k in ('MBC','ML')}
    years={};seasons={};cases=0;rows=0
    def accumulate(a,p,y,w):
        y=y.astype(np.float64);p=np.maximum(p,0).astype(np.float64);w=w.astype(np.float64)
        e=p-y
        a+=np.array([w.sum(),w@e,w@(e*e),w@np.abs(e),w@y,w@p,w@(y*y),w@(p*p),w@(y*p),len(y)])
    season=lambda m:'DJF' if m in (12,1,2) else 'MAM' if m in (3,4,5) else 'JJA' if m in (6,7,8) else 'SON'
    for fp,n,_,d in records('valid'):
        mm=int(d['month']); data=np.memmap(fp,dtype=np.float32,mode='r',shape=(n,NC))
        for case in d['case_ranges']:
            sl=slice(case['offset'],case['offset']+case['count'])
            block=data[sl]
            for start in range(0,len(block),50000):
                bb=block[start:start+50000];y=bb[:,0];w=bb[:,1]
                baseline=bb[:,8]
                residual=model.predict(np.asarray(bb[:,2:],dtype=np.float32))
                pred=np.maximum(0,baseline+residual)
                key=(str(case['year']),season(mm))
                for typ,pp in (('MBC',baseline),('ML',pred)):
                    accumulate(totals[typ],pp,y,w)
                    accumulate(years.setdefault((str(case['year']),typ),np.zeros(10)),pp,y,w)
                    accumulate(seasons.setdefault((season(mm),typ),np.zeros(10)),pp,y,w)
                rows+=len(bb)
            cases+=1
        print(f'VALIDATED MONTH {mm:02d}: total={rows:,} rows',flush=True)
    assert cases==365 and rows==75044000
    def metrics(s):
        ws,se,sse,sa,sy,sp,sy2,sp2,syp,nn=s
        a=sy2/ws-(sy/ws)**2;b=sp2/ws-(sp/ws)**2
        r=(syp/ws-sy*sp/ws**2)/np.sqrt(a*b) if a>0 and b>0 else float('nan')
        return dict(rmse=float(np.sqrt(sse/ws)),mae=float(sa/ws),bias=float(se/ws),pearson_r=float(r),rows=int(nn))
    summary={k:metrics(v) for k,v in totals.items()}
    full=json.loads((OUT/'FULLGRID_ML_FEATURE_STORE_MANIFEST.json').read_text())
    result=dict(model=model_kind,summary=summary,year={f'{a}_{b}':metrics(v) for (a,b),v in years.items()},
                season={f'{a}_{b}':metrics(v) for (a,b),v in seasons.items()},
                exact_rows=rows,source_feature_manifest=str(OUT/'FULLGRID_ML_FEATURE_STORE_MANIFEST.json'),
                validation_period=[2020,2021],training_period=list(range(2005,2020)),test_period_unread=[2022,2023,2024,2025])
    jsonwrite(MODEL_DIR/f'{model_kind.upper()}_VALIDATION_FULLGRID.json',result)
    print('PASS VALIDATION ALL',rows,'rows',summary,flush=True)


def selftest():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        path=Path(td)/'toy.f32'
        a=np.arange(6*NC,dtype=np.float32).reshape(6,NC)
        path.write_bytes(a.tobytes())
        mm=np.memmap(path,dtype=np.float32,mode='r',shape=(6,NC))
        assert np.array_equal(mm[:,2:],a[:,2:])
    print('PASS model input format and feature column offset test')

if __name__=='__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('mode',choices=['selftest','pack','train-lgbm','train-catboost','score-lgbm','score-catboost'])
    ap.add_argument('--split',choices=['train','valid'],default='train')
    args=ap.parse_args()
    if args.mode=='selftest':selftest()
    elif args.mode=='pack':pack_targets(args.split)
    elif args.mode=='train-lgbm':lightgbm_train()
    elif args.mode=='train-catboost':catboost_train()
    elif args.mode=='score-lgbm':score('lightgbm')
    elif args.mode=='score-catboost':score('catboost')
