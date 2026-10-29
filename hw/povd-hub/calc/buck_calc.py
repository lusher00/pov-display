#!/usr/bin/env python3
"""povd-hub 5 V stage: LM5145 + CSD19533Q5A (HS) + CSD19502Q5B (LS), 2.2 uH, 400 kHz.
Steady-state, losses, current limit, and small-signal loop (voltage mode, VIN feedforward, type 3)."""
import numpy as np, math
import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt

VOUT_SET = 0.8*(1+10e3/1.91e3)


FSW = 10000/24.9*1e3               # Hz
L = 2.2e-6; DCR = 4e-3             # WE-HCI 1365 spec <= 5 mOhm
VCC = 7.5
# MOSFETs (datasheet typ; hot factor from 4500 ppm/C at ~100 C junction)
HOT = 1+0.0045*(100-25)
import os
FETS = {
 'CSD19533Q5A': dict(r6=8.7e-3, r10=7.8e-3, r10max=9.4e-3, qg10=27e-9, qgd=4.9e-9, qgs=7.9e-9, vpl=4.6, qoss=75e-9*(40/50)**0.5, qrr=163e-9, rg=1.2),
 'BSC040N08NS5': dict(r6=4.8e-3, r10=3.4e-3, r10max=4.0e-3, qg10=43e-9, qgd=9.3e-9, qgs=14.3e-9, vpl=4.8, qoss=52e-9, qrr=43e-9, rg=1.1),
 'BSC028N06LS3': dict(r6=2.6e-3, r10=2.3e-3, r10max=2.8e-3, qg10=132e-9, qgd=10e-9, qgs=31e-9, vpl=3.0, qoss=83e-9*(40/30)**0.5, qrr=58e-9, rg=1.0),
}
Q2 = dict(FETS[os.environ.get('HS','CSD19533Q5A')]); Q3 = dict(FETS[os.environ.get('LS','BSC040N08NS5')])
def r_at(q,vgs,maxv=False):
    r = q['r6'] + (q['r10']-q['r6'])*(vgs-6)/4
    return r*(q['r10max']/q['r10'] if maxv else 1)
def qg_at(q,vgs):  # gate charge at vgs, linear above ~plateau end (Qgs+Qgd at ~4.5 V)
    qp = q['qgs'] + q['qgd']
    return qp + (q['qg10']-qp)*(vgs-q['vpl'])/(10-q['vpl'])
QG2, QG3 = qg_at(Q2,VCC), qg_at(Q3,VCC)
RDRV_UP, RDRV_DN = 1.5, 0.9; RG_INT = 1.0
VPL = 4.5   # plateau estimate

def steady(vin, iout, verbose=False):
    d = VOUT_SET/vin
    di = VOUT_SET*(1-d)/(L*FSW)
    ipk = iout+di/2; ival = iout-di/2
    irms_hs = math.sqrt(d*(iout**2+di**2/12)); irms_ls = math.sqrt((1-d)*(iout**2+di**2/12))
    r2 = r_at(Q2,VCC)*HOT; r3 = r_at(Q3,VCC)*HOT
    p_cond_hs = irms_hs**2*r2; p_cond_ls = irms_ls**2*r3
    # HS switching: Qgd-dominated transitions
    i_on = (VCC-Q2['vpl'])/(RDRV_UP+Q2['rg']); i_off = Q2['vpl']/(RDRV_DN+Q2['rg'])
    t_r = Q2['qgd']/i_on; t_f = Q2['qgd']/i_off
    p_sw_hs = 0.5*vin*(ival*t_r + ipk*t_f)*FSW
    p_oss = 0.5*(Q2['qoss']+Q3['qoss'])*vin*FSW* (vin/40)**0.5   # Qoss values normalised to 40 V, scaled with sqrt(V)
    p_rr = Q3['qrr']*vin*FSW
    p_dt = 0.75*(ival*14e-9 + ipk*14e-9)*FSW   # body diode in 2 x 14 ns dead time, Vf 0.75
    p_gate = (QG2+QG3)*VCC*FSW               # dissipated in drivers + Rg
    i_vcc = (QG2+QG3)*FSW + 3e-3              # + controller quiescent ~3 mA (assumed)
    p_ldo = i_vcc*(vin-VCC)
    p_l = (iout**2+di**2/12)*DCR + 0.25       # core loss allowance 0.25 W (assumed)
    p_snub = 330e-12*vin**2*FSW
    pout = VOUT_SET*iout
    ploss = p_cond_hs+p_cond_ls+p_sw_hs+p_oss+p_rr+p_dt+p_gate+p_ldo+p_l+p_snub
    eff = pout/(pout+ploss)
    iin = (pout+ploss)/vin
    icin_rms = iout*math.sqrt(d*(1-d))
    return dict(vin=vin,iout=iout,d=d,ton=d/FSW,di=di,ipk=ipk,ival=ival,
                p_cond_hs=p_cond_hs,p_cond_ls=p_cond_ls,p_sw_hs=p_sw_hs,p_oss=p_oss,p_rr=p_rr,p_dt=p_dt,
                p_q2=p_cond_hs+p_sw_hs+p_oss/2+2/3*p_rr, p_q3=p_cond_ls+p_dt+1/3*p_rr,
                p_gate=p_gate,i_vcc=i_vcc,p_ldo=p_ldo,p_ic=p_ldo+p_gate*0.6,p_l=p_l,p_snub=p_snub,
                ploss=ploss,eff=eff,iin=iin,icin_rms=icin_rms)

# current limit (valley, RDS(on) sensing on Q3; source tempco cancels RDS tempco)
R_ILIM = 360
I_RDSON = (180e-6, 200e-6, 220e-6)
def ilim():
    out=[]
    for lab,irs,r in (('min',I_RDSON[0],r_at(Q3,VCC,True)),('typ',I_RDSON[1],r_at(Q3,VCC)),('max',I_RDSON[2],r_at(Q3,VCC)*0.9)):
        iv = irs*R_ILIM/r
        out.append((lab,iv))
    return out

# ---------- small signal ----------
caps = ([('470u polymer',470e-6,10e-3,1.5e-9)]*4 + [('22u X7R@5V',14e-6,3e-3,0.6e-9)]*6 +
        [('220u polymer',220e-6,15e-3,1.5e-9)]*4 + [('10u X5R@5V',5e-6,5e-3,0.5e-9)]*8)
def Zout(s, scale=1.0):
    y = 0
    for _,c,esr,esl in caps: y = y + 1/(esr + 1/(s*c*scale) + s*esl)
    return 1/y
KFF = 15.0
R_FB1, R_FB2, R_C1, C_C1, C_C2, R_C2, C_C3 = 10e3, 1.91e3, 11e3, 12e-9, 68e-12, 680, 6.8e-9
A0 = 10**(94/20); GBW = 6.5e6; wa = 2*math.pi*GBW/A0
def Gc(s):
    Zf = 1/(1/(R_C1+1/(s*C_C1)) + s*C_C2)
    Zi = 1/(1/R_FB1 + 1/(R_C2+1/(s*C_C3)))
    A = A0/(1+s/wa)
    ideal = Zf/Zi
    return ideal/(1+(1+ideal)/A)
def Gvd(s, rload, scale=1.0):
    Zc = Zout(s,scale); Zp = 1/(1/Zc+1/rload)
    return KFF*Zp/(s*L+DCR+Zp)
def loop(f, rload, scale=1.0):
    s = 2j*math.pi*f
    # sampling / PWM delay ~ half period approx
    delay = np.exp(-s*100e-9)   # ~100 ns comparator + driver + dead-time delay
    return Gvd(s,rload,scale)*Gc(s)*delay
def margins(rload, scale=1.0):
    f = np.logspace(1, math.log10(FSW/2), 6000)
    T = loop(f, rload, scale); mag = 20*np.log10(abs(T)); ph = np.degrees(np.unwrap(np.angle(T)))
    i = np.where(np.diff(np.sign(mag)))[0]
    fc = f[i[-1]]; pm = 180+ph[i[-1]]
    while pm>180: pm-=360
    j = np.where(np.diff(np.sign(ph+180)))[0]
    gm = -mag[j[-1]] if len(j) else float('nan')
    return fc, pm, gm, f, mag, ph

if __name__=='__main__':
    import json
    print('VOUT set %.3f V, fsw %.1f kHz'%(VOUT_SET,FSW/1e3))
    print('Qg at 7.5 V: Q2 %.1f nC, Q3 %.1f nC, total %.1f nC'%(QG2*1e9,QG3*1e9,(QG2+QG3)*1e9))
    print('L0 resonance: total C %.0f uF'%(sum(c for _,c,_,_ in caps)*1e6))
    for vin in (12,24,36,40):
        for io in (5,15):
            r=steady(vin,io)
            print('VIN %2d IOUT %2d: D %.3f ton %4.0f ns  dI %.2f A pk %.1f  Iin %.2f A  eff %.1f%%  loss %.2f W | Q2 %.2f Q3 %.2f L %.2f IC(LDO+drv) %.2f snub %.2f | Ivcc %.1f mA  LDO %.2f W  Icin_rms %.1f A'%(
                vin,io,r['d'],r['ton']*1e9,r['di'],r['ipk'],r['iin'],r['eff']*100,r['ploss'],r['p_q2'],r['p_q3'],r['p_l'],r['p_ic'],r['p_snub'],r['i_vcc']*1e3,r['p_ldo'],r['icin_rms']))
    print('valley current limit (R_ILIM %d):'%R_ILIM, [(a,round(b,1)) for a,b in ilim()])
    for vin in (12,24,40):
        r=steady(vin,15)
        iv_min=ilim()[0][1]
        print('  VIN %d: dI %.2f, min avg out at limit %.1f A, peak at typ limit %.1f A'%(vin,r['di'],iv_min+r['di']/2,ilim()[1][1]+r['di']))
    f0 = 1/(2*math.pi*math.sqrt(L*sum(c for _,c,_,_ in caps)))
    print('f0 %.0f Hz; fz1 %.0f, fz2 %.0f, fp1 %.0f, fp2 %.0f Hz; mid-band EA gain %.1f'%(
        f0, 1/(2*math.pi*R_C1*C_C1), 1/(2*math.pi*(R_FB1+R_C2)*C_C3), 1/(2*math.pi*R_C2*C_C3),
        1/(2*math.pi*R_C1*C_C1*C_C2/(C_C1+C_C2)), R_C1*(R_FB1+R_C2)/(R_FB1*R_C2)))
    fig,(a1,a2)=plt.subplots(2,1,figsize=(9,7),sharex=True)
    for lab,rl,sc in (('15 A, nominal C',5/15,1.0),('1 A, nominal C',5/1,1.0),('15 A, C -40%',5/15,0.6),('15 A, C +30%',5/15,1.3),('15 A, blade caps not fitted',5/15,None)):
        if sc is None:
            saved=list(caps); caps[:] = [c for c in caps if c[0] not in ('220u polymer','10u X5R@5V')]
            fc,pm,gm,f,mag,ph=margins(rl,1.0); caps[:]=saved
        else:
            fc,pm,gm,f,mag,ph=margins(rl,sc)
        print('%-28s fc %6.1f kHz  PM %5.1f deg  GM %5.1f dB'%(lab,fc/1e3,pm,gm))
        a1.semilogx(f,mag,label='%s: fc %.0f kHz, PM %.0f°'%(lab,fc/1e3,pm)); a2.semilogx(f,ph)
    a1.axhline(0,color='k',lw=0.5); a2.axhline(-180,color='k',lw=0.5)
    a1.set_ylabel('loop gain (dB)'); a2.set_ylabel('phase (deg)'); a2.set_xlabel('Hz'); a1.legend(fontsize=7); a1.grid(True,which='both',lw=0.3); a2.grid(True,which='both',lw=0.3)
    a1.set_title('LM5145 5 V loop (VIN-independent: feedforward k=15)')
    fig.savefig(os.path.join(os.path.dirname(os.path.abspath(__file__)),'buck_loop.png'),dpi=120,bbox_inches='tight')
