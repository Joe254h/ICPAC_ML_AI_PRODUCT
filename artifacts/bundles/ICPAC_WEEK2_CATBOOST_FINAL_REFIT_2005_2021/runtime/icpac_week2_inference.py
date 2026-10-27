#!/usr/bin/env python3
"""ICPAC 0.05-degree Week-2 ECMWF/MBC/CatBoost prediction adapter.

Interface only; upstream ECMWF rainfall and 30 atmospheric predictors must
follow the audited training preprocessing. No observation targets are required.
Do not treat an unverified real-time feed as the audited reforecast source.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from datetime import date
from pathlib import Path
import numpy as np
from catboost import CatBoostRegressor

FEATURES = ['X_mean_mmweek','X_spread_mmweek','latitude_deg','longitude_deg',
            'doy_sin','doy_cos','MBC_forecast_mmweek'] + [f'atmospheric_PC{i:02}' for i in range(1,18)]
N = 205999


def sha256(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(8*1024*1024),b''):
            h.update(block)
    return h.hexdigest()


def valid_date(s):
    d=date.fromisoformat(s)
    if s != d.isoformat():
        raise ValueError('init_date must be YYYY-MM-DD')
    return d


class ICPACWeek2Predictor:
    def __init__(self, bundle_dir, verify_checksums=True, thread_count=4):
        self.root=Path(bundle_dir).resolve()
        self.manifest=json.loads((self.root/'manifest.json').read_text())
        if verify_checksums:
            for name, digest in self.manifest['files_sha256'].items():
                path=self.root/name
                if not path.is_file() or sha256(path)!=digest:
                    raise RuntimeError(f'Inference bundle checksum mismatch: {name}')
        schema=json.loads((self.root/'config/feature_schema.json').read_text())
        if schema['features'] != FEATURES or schema['cell_count'] != N:
            raise RuntimeError('Frozen predictor schema mismatch')
        with np.load(self.root/'artifacts/authoritative_icpac11_mask.npz',allow_pickle=False) as z:
            self.lat=np.asarray(z['latitude'],dtype=np.float64)
            self.lon=np.asarray(z['longitude'],dtype=np.float64)
            self.domain=np.asarray(z['domain_mask'],dtype=bool)
            self.country_id=np.asarray(z['country_id']) if 'country_id' in z else None
        if self.domain.shape!=(800,700) or self.lat.shape!=(800,) or self.lon.shape!=(700,):
            raise RuntimeError('Unexpected authoritative domain geometry')
        self.rr,self.cc=np.nonzero(self.domain)
        if len(self.rr)!=N:
            raise RuntimeError('Unexpected authoritative mask cell count')
        with np.load(self.root/'artifacts/mbc_monthly_prior500_cap3.npz',allow_pickle=False) as z:
            self.factors=np.asarray(z['factors'],dtype=np.float32)
            if not np.array_equal(self.rr,z['row_indices']) or not np.array_equal(self.cc,z['col_indices']):
                raise RuntimeError('MBC factor indices do not match authoritative grid')
        if self.factors.shape!=(12,N) or not np.isfinite(self.factors).all() or np.any(self.factors < 0):
            raise RuntimeError('Invalid frozen MBC factors')
        with np.load(self.root/'artifacts/pca_atmos30_refit2005_2021.npz',allow_pickle=False) as z:
            self.pca_mean=np.asarray(z['mean'],dtype=np.float64)
            self.pca_scale=np.asarray(z['scale'],dtype=np.float64)
            self.pca_basis=np.asarray(z['components'][:17].T,dtype=np.float64)
            if 'training_years' in z and list(z['training_years'])!=list(range(2005,2022)):
                raise RuntimeError('PCA must be fitted on 2005–2021 development years')
        if self.pca_mean.shape!=(30,) or self.pca_scale.shape!=(30,) or self.pca_basis.shape!=(30,17) or np.any(self.pca_scale<=0):
            raise RuntimeError('PCA dimensions/scaling invalid')
        self.model=CatBoostRegressor(thread_count=thread_count)
        self.model.load_model(str(self.root/'artifacts/catboost_residual_fullrows.cbm'))
        if len(self.model.feature_names_) != 24:
            raise RuntimeError(f'CatBoost expects {len(self.model.feature_names_)} features, not 24')
        self.climatology=None
        cp=self.root/'artifacts/train_only_monthly_climatology.npz'
        if cp.exists():
            with np.load(cp,allow_pickle=False) as z:
                c=np.asarray(z['mean_mmweek'],dtype=np.float32)
                if c.shape!=(12,N) or not np.isfinite(c).all():
                    raise RuntimeError('Train-only climatology invalid')
                self.climatology=c

    def _date_guard(self, init_date, operational_feed_verified):
        d=valid_date(init_date)
        if d.year >= 2025 and not operational_feed_verified:
            raise RuntimeError('Real-time ECMWF source not yet harmonized. Complete forecast-cycle, units, ensemble, lead, and grid QC; then acknowledge operational_feed_verified=True.')
        return d

    def build_features(self, init_date, raw_week2_mm, spread_week2_mm, atmospheric30_interpolated,
                       *, operational_feed_verified=False):
        """Build the exact 24 model inputs from already aligned 205999-cell ECMWF arrays.

        atmospheric30_interpolated: columns must follow training source Q mean/spread order;
        no raw-pressure input or grid interpolation is performed inside this method.
        """
        d=self._date_guard(init_date,operational_feed_verified)
        raw=np.asarray(raw_week2_mm,dtype=np.float32)
        spread=np.asarray(spread_week2_mm,dtype=np.float32)
        atm=np.asarray(atmospheric30_interpolated,dtype=np.float64)
        if raw.shape!=(N,) or spread.shape!=(N,) or atm.shape!=(N,30):
            raise ValueError('Expected raw/spread (205999,) and aligned atmos (205999,30)')
        if not (np.isfinite(raw).all() and np.isfinite(spread).all() and np.isfinite(atm).all()):
            raise ValueError('Nonfinite ECMWF features')
        if np.any(raw<0) or np.any(spread<0):
            raise ValueError('Negative ECMWF rainfall/spread; upstream QC required')
        pcs=((atm-self.pca_mean)/self.pca_scale)@self.pca_basis
        doy=d.timetuple().tm_yday
        f=np.empty((N,24),dtype=np.float32)
        f[:,0]=raw
        f[:,1]=spread
        f[:,2]=self.lat[self.rr]
        f[:,3]=self.lon[self.cc]
        f[:,4]=math.sin(2*math.pi*doy/365.2425)
        f[:,5]=math.cos(2*math.pi*doy/365.2425)
        f[:,6]=raw*self.factors[d.month-1]
        f[:,7:]=pcs.astype(np.float32)
        return f

    def _check_features(self, f, d):
        if f.shape!=(N,24) or not np.isfinite(f).all():
            raise ValueError('Expected all 205999 cells and 24 finite predictors in frozen order')
        if np.any(f[:,0]<0) or np.any(f[:,1]<0) or np.any(f[:,6]<0):
            raise ValueError('Invalid negative rainfall or spread')
        if not np.allclose(f[:,2],self.lat[self.rr],atol=2e-4,rtol=0):
            raise ValueError('Latitude/grid order mismatch')
        if not np.allclose(f[:,3],self.lon[self.cc],atol=2e-4,rtol=0):
            raise ValueError('Longitude/grid order mismatch')
        doy=d.timetuple().tm_yday
        if not np.allclose(f[:,4],math.sin(2*math.pi*doy/365.2425),atol=2e-6,rtol=0) or not np.allclose(f[:,5],math.cos(2*math.pi*doy/365.2425),atol=2e-6,rtol=0):
            raise ValueError('Initialization date (DOY) mismatch')
        expected=f[:,0]*self.factors[d.month-1]
        if not np.allclose(f[:,6],expected,atol=5e-3,rtol=5e-4):
            raise ValueError('MBC factor or initialization-month mismatch')

    def predict(self, features, init_date, policy='catboost_full', *, operational_feed_verified=False):
        """Return 205999 nonnegative mm/week predictions in authoritative mask order.

        catboost_full: clip(MBC + CatBoost residual, 0)
        global_alpha075: 0.25*clip(MBC,0) + 0.75*catboost_full
        mam_protected: MBC in Mar-May, otherwise global_alpha075
        mbc_only: MBC
        """
        d=self._date_guard(init_date,operational_feed_verified)
        f=np.asarray(features,dtype=np.float32)
        self._check_features(f,d)
        base=np.maximum(0,f[:,6]).astype(np.float64)
        if policy=='mbc_only':
            return base.astype(np.float32)
        if policy not in ('catboost_full','global_alpha075','mam_protected'):
            raise ValueError('Unknown policy; choose catboost_full, global_alpha075, mam_protected, or mbc_only')
        if policy=='mam_protected' and d.month in (3,4,5):
            return base.astype(np.float32)
        correction=np.asarray(self.model.predict(f),dtype=np.float64)
        complete=np.maximum(0,base+correction)
        if policy=='catboost_full':
            result=complete
        else:
            result=0.25*base+0.75*complete
        if not np.isfinite(result).all() or np.any(result<0):
            raise RuntimeError('Invalid model outputs')
        return result.astype(np.float32)

    def to_grid(self, prediction):
        p=np.asarray(prediction,dtype=np.float32)
        if p.shape!=(N,):raise ValueError('Expected 205999 flat predictions')
        grid=np.full((800,700),np.nan,dtype=np.float32)
        grid[self.rr,self.cc]=p
        return grid

    def anomaly_vs_training_climatology(self, prediction, init_date):
        if self.climatology is None:
            raise RuntimeError('Training climatology not present in bundle')
        d=valid_date(init_date)
        return np.asarray(prediction,dtype=np.float32)-self.climatology[d.month-1]


def main():
    ap=argparse.ArgumentParser(description='Run ICPAC model inference from verified 205999x24 feature matrix')
    ap.add_argument('--bundle',required=True)
    ap.add_argument('--features',required=True,help='Numpy .npy matrix of shape (205999,24), already in authoritative order')
    ap.add_argument('--init-date',required=True,help='ECMWF initialization date YYYY-MM-DD')
    ap.add_argument('--policy',choices=['catboost_full','global_alpha075','mam_protected','mbc_only'],default='catboost_full')
    ap.add_argument('--output',required=True,help='Output compressed .npz with rainfall and 800x700 grid')
    ap.add_argument('--operational-feed-verified',action='store_true',help='Use only after separate real-time ECMWF harmonization/QC is documented')
    ap.add_argument('--threads',type=int,default=4)
    a=ap.parse_args()
    pred=ICPACWeek2Predictor(a.bundle,thread_count=a.threads)
    x=np.load(a.features,allow_pickle=False)
    flat=pred.predict(x,a.init_date,a.policy,operational_feed_verified=a.operational_feed_verified)
    dest=Path(a.output)
    if dest.exists():raise FileExistsError('Refusing to overwrite prediction output')
    dest.parent.mkdir(parents=True,exist_ok=True)
    np.savez_compressed(dest,rainfall_mmweek=flat,grid_mmweek=pred.to_grid(flat),
        init_date=np.array(a.init_date),policy=np.array(a.policy),units=np.array('mm/week'))
    print('PASS forecast',a.init_date,a.policy,'cells=',len(flat),'saved=',dest)


if __name__=='__main__': main()
