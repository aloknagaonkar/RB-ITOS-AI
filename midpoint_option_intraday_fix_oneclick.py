#!/usr/bin/env python3
"""Switch same-session exact option acquisition to read-only intraday minutes."""
from pathlib import Path
import base64,hashlib,subprocess,sys,zlib
from datetime import datetime,timezone
ROOT=Path.cwd()
REL='backend/market_lab/midpoint_strategy/materialize_option_observation.py'
BEFORE='b285542e3ab84719ccbd54c7e6552fb30e1dd82256dfdf969cf98a4f749d4558'
AFTER='b1a5faf1025424b12936e2d3def9cd9a71c0d932037a88c8feea0ea71b7b04f8'
PAYLOAD='c-oy;TW{Mo6n@vQAh?G~fUPtEHlQwCz)if(SYjKoT{Or7f{`ejizKQf<x8{t_Z?D{Emv+9EHI)Ac|M-=ovSd$gXn9?B|~gWBaLo&TnL_PBnr(%u8<apBE<?Ssb)yif_*@;%n?mAlPII|iD|SFrBtEkP4DJ^Ovcl}{Ez-4jh<K@qhhC5B1hfK?IkIF3^R8MQQE*RcVPw>$!W^JF;X2(#G_(zP0c;}%R{K!RZJ;(>c&Qui+2~lcHh14Uc84Dwk^2ap*#5N-rRJrt~~FSS-Zf3l`)Ph&GRK%OlR}S7c#iK9L{EBKKXMv4$+l>ZMo1$X(~0?yAhzOM8f=HCPNQn>?KlUh>)bzrDTL4o)yCE&Oy>@sXVWKCzn8&V)gUiO62vuP!*CfLi3E(IOe&te_QP-s9vS~vEDL;N6$$M&GL1<kO~@;>Xlo6mFyD)JD^B1*g}k(-+&`ok<#6f610rDCdS^h1yB}Bi!Dj{nh~|4vDgp=ffF%B*5@_K!fv{TJu|yyR_*wF-hzuoM)_Xz(QNK{gT>Woj{24;9|M>4%$(M3SbA2Q(XGwsuFub`+M!h&2i|1yzd$NloBIH3F}@n!Uf+$zzXK#5&xT|KZ@&C9=84{+U*2KQ^J11DV~Zc4?ng8hIqN~ZBV=Ppf?OR>;Xp3SjOBW2SNxc%NOF5@pFjXagai%AkjCH<C*tGd1i~F8s}za*b6G;{>0QD4W+^mOb0rcXAunG=tP=0dSRIRX>Tku;qK}8R2)S&2%Ebl>4Ls*s?mnQLt$_`mC-9$wLTbO$hK3d~-Tkak1RhJp5?6YIvI-b<>f4JkK>5{jBXfKl!ha{G1ynDP6DnM?YV}0v0K2gh;EAmuR<5_VQc|uMn(dTk*>KDCNfgA@o<4^r#l~oTFA?yDjM1(1@@=pO=3r@b^s)0UvEB_(-^Ps!o3F#YC;Z^So@BV??EAy)`3Gbm9`fG!6mVhr8Gj<f@%;AA5HNJNFAq&39PVpWjK!hdd^#IeZbsHbtBGC#F_keE#T5%s^@l~mxBNR7%H84gNB}s*mXUTibs5|*`G;KXRMb`B6&z4#9;a4==NE7P)}*iPo+RUWshRSh*e>WDg*vbTFD)~`pTp_3vf(FZn%My{0i6aCAV(}KpjZGMT1Xzz6wFCe7TL-TKj?5LkfKsbpcFa(Bjd#5wjHGcY6@C_UpO#RO#tWF2`p|Xg7g9(Ifqpaq6c^g$z9kI1-n~8Xd<)jb0Oro54Af8%^N@Hoh%S89lmp1trR)WEaNRvmMZopzyq_yxyAr?+N!tDaQp9J|AS2;v8mDst}c;&So0br!M@P&0TW18gizYx{u?xcCO0QD`r!!Og-lbaL!6qfZWH|=V>GSO4s>m$tQBGsq8dW35A}DeegBPB0(8Z*`R(FzzPKG+llk!WW;7mL<JZXmy=$}>%3)MBQ3GbRY^}T*Euk4tcP*&;^_y{=jkTw$27o>~(EHZ<L(s7e{rCjyiI5frq?6y6xqOS#*^}OJ4X)p)MxFl*r{jXx-`{oIP+ym+{!!5i4k{LOXS$6kb2t+*OK}h3o6*&DG8)gx@XO$GPA1d&Xfh@<=wjyj`P@)()PZ`hx1W=CV9N}M+AAP7hACny3@lXx24-6pmG(W$>0=75vxk18knyL13jmbFj`J-6guj+F*IXNT<E@uH1dM`V_5=~<!{`9sQEtAm9~4A9*~cbxdIhwZ0rCtb`1w@^UhKem$OveRFv?O$#=Zp#H(alXDwBk7VK_0HLk%$%v?aog<R*qphT45`nH9=+j_g3P#-M!vq5~yQY65kkG9);KWyku6`9_C^X%gzKpWqo?vlu<6EcdOGf*02~s^GGo^HtD8&qn^Gp{;Ehuxd(&6+Nyr)d6M!(#YgNGmSc^T2MS@hbL3#xS<ukNvJLrtekLut?E5a*;3h*#QUUh`Xwga(#F70w+7oIVOWH3y9B=ea+;ZMKU3WZF*7?MxDu)cc<)~rci6!'
if not (ROOT/'frontend/package.json').is_file(): raise SystemExit('STOP: run from RB-ITOS-AI root')
p=ROOT/REL
original=p.read_bytes()
current=hashlib.sha256(original).hexdigest()
if current not in (BEFORE,AFTER): raise SystemExit('STOP: source differs from reviewed version; nothing changed')
if current==AFTER: print('Source already updated; no service restarted'); raise SystemExit(0)
backup=ROOT/'data/backups'/('midpoint-option-intraday-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
backup.mkdir(parents=True,exist_ok=False)
q=backup/REL;q.parent.mkdir(parents=True);q.write_bytes(original)
p.write_bytes(zlib.decompress(base64.b85decode(PAYLOAD)))
try:
    subprocess.run([str(ROOT/'.venv/bin/python'),'-m','pytest','-q','tests/test_midpoint_m25b_option_observation.py','tests/test_midpoint_m3_live_shadow_ui.py'],check=True)
    subprocess.run(['git','diff','--check'],check=True)
except Exception as exc:
    p.write_bytes(original)
    raise SystemExit(f'STOP: validation failed ({exc}); source restored') from exc
print('PASS: same-day exact option acquisition now uses intraday 1m source; no service restarted.')
print('Backup:',backup)
