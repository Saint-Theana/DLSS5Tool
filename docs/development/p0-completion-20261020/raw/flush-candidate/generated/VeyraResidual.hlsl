#include "NrProtection.hlsli"
Texture2D<float4> baseTex:register(t0);
Texture2D<float4> nrInput:register(t1);
Texture2D<float4> nrFinal:register(t2);
RWTexture2D<float4> outputTex:register(u0);
cbuffer Params:register(b0){float total;float darken;float brighten;float color;float luminance;float protectionEnabled;float featherPixels;float signedHdr;float4 regions[4];float residualInput;float residualMultiplier;float residualSaturation;float residualLightness;float shadowStructureMultiplier;float reflectionGlowMultiplier;float lumaRec2100;float outputTransfer;}
// Extrapolating a negative linear-light residual can cross zero even when
// both input images contain shadow detail. Continue below the unboosted
// endpoint with a positive, tangent-matched curve instead of hard clipping.
// Identity and 0..1 mixing remain exact. Signed HDR gamut components remain
// signed; this is a residual-strength safeguard, not an input/output gamma.
float shadowSafe(float base,float rawDelta,float requestedDelta){
    float anchorDelta=min(rawDelta,0.0);
    float anchor=base+anchorDelta;
    if(base>=0&&anchor>0&&requestedDelta<anchorDelta)
        return anchor/(1.0+(anchorDelta-requestedDelta)/anchor);
    return base+requestedDelta;
}
// Bilateral resampling of the change uses the preserved high-resolution base
// as the edge guide. It never interpolates the high-resolution base itself.

float3 NrLumaWeights() {
    return lumaRec2100>0.5?float3(0.2627,0.6780,0.0593):float3(0.2126,0.7152,0.0722);
}
// Same ST2084/HLG normalization as video_export's CPU reference. Only used
// when a same-card GPU sink consumes the output, never by realtime/CPU paths.
float3 NrEncodeOutput(float3 radiance) {
    if(outputTransfer<0.5) return radiance;
    float3 x=max(radiance,0);
    float mode=outputTransfer>=4?outputTransfer-4:outputTransfer;
    precise float3 coded;
    if(mode<1.5) {
        precise float3 v=pow(x,2610.0/16384.0);
        precise float3 numerator=3424.0/4096.0+(2413.0/128.0)*v;
        precise float3 denominator=1.0+(2392.0/128.0)*v;
        coded=saturate(pow(numerator/max(denominator,1e-7),2523.0/32.0));
    } else {
        float a=0.17883277,b=1.0-4.0*a,c=0.5-a*log(4.0*a);
        float3 low=sqrt(3.0*x),high=a*log(max(12.0*x-b,1e-7))+c;
        coded=saturate(float3(x.r<=1.0/12.0?low.r:high.r,x.g<=1.0/12.0?low.g:high.g,x.b<=1.0/12.0?low.b:high.b));
    }
    // Typed RGBA16F UAV stores may truncate; CPU astype(float16) rounds to
    // nearest-even. Explicitly quantize before storing to keep that contract.
    if(outputTransfer>=4) {
        // f32tof16 is permitted to truncate too. Find the adjacent half values
        // explicitly and select the nearest, choosing even at an exact tie.
        uint3 lo=f32tof16(coded);
        lo-=uint3(f16tof32(lo)>coded);
        precise float3 midpoint=(f16tof32(lo)+f16tof32(lo+1))*0.5;
        bool3 up=(coded>midpoint)|((coded==midpoint)&((lo&1)!=0));
        return f16tof32(lo+uint3(up));
    }
    return coded;
}
float3 NrToLinear(float3 color) {
    return float3(
        color.r <= 0.04045 ? color.r / 12.92 : pow(max(color.r + 0.055, 0.0) / 1.055, 2.4),
        color.g <= 0.04045 ? color.g / 12.92 : pow(max(color.g + 0.055, 0.0) / 1.055, 2.4),
        color.b <= 0.04045 ? color.b / 12.92 : pow(max(color.b + 0.055, 0.0) / 1.055, 2.4));
}
float3 NrRgbToHsl(float3 rgb) {
    float hi=max(rgb.r,max(rgb.g,rgb.b)), lo=min(rgb.r,min(rgb.g,rgb.b));
    float d=hi-lo, safe=max(d,1e-6), light=(hi+lo)*0.5;
    float hue=hi==rgb.r?(rgb.g-rgb.b)/safe:hi==rgb.g?(rgb.b-rgb.r)/safe+2:(rgb.r-rgb.g)/safe+4;
    hue=frac(hue/6.0+1.0);
    float sat=d/max(1.0-abs(2.0*light-1.0),1e-6);
    return float3(d>1e-6?hue:0,saturate(d>1e-6?sat:0),light);
}
float NrHue(float p,float q,float t) {
    t=frac(t+1.0);
    return t<1.0/6.0?p+(q-p)*6.0*t:t<0.5?q:t<2.0/3.0?p+(q-p)*(2.0/3.0-t)*6.0:p;
}
float3 NrHslToRgb(float3 hsl) {
    float h=hsl.x,s=hsl.y,l=hsl.z,q=l<0.5?l*(1+s):l+s-l*s,p=2*l-q;
    return saturate(s<=1e-6?float3(l,l,l):float3(NrHue(p,q,h+1.0/3.0),NrHue(p,q,h),NrHue(p,q,h-1.0/3.0)));
}
float3 NrApplyFine(float3 original,float3 residual) {
    float3 adjusted=residual*residualMultiplier;
    if(signedHdr>0.5) {
        if(residualMultiplier==1 && residualSaturation==1 && residualLightness==1 &&
           shadowStructureMultiplier==1 && reflectionGlowMultiplier==1) return original+residual;
        // Match hdr_fine_controls: classify in linear light, then split the
        // directed residual into luminance/chroma. Never use SDR HSL/clipping.
        float dy=dot(adjusted,NrLumaWeights());
        adjusted*=dy<0?shadowStructureMultiplier:(dy>0?reflectionGlowMultiplier:1);
        float luma=dot(adjusted,NrLumaWeights());
        return original+luma*residualLightness+(adjusted-luma)*residualSaturation;
    }
    float3 result=original+adjusted;
    bool nonNeutral=abs(residualSaturation-1.0)>=1e-6 || abs(residualLightness-1.0)>=1e-6 ||
        abs(shadowStructureMultiplier-1.0)>=1e-6 || abs(reflectionGlowMultiplier-1.0)>=1e-6;
    if(nonNeutral) {
        float3 candidate=original+adjusted;
        if(signedHdr<=0.5) candidate=saturate(candidate);
        float3 classification=signedHdr>0.5?adjusted:NrToLinear(candidate)-NrToLinear(original);
        float dy=dot(classification,float3(0.2126,0.7152,0.0722));
        float directional=dy<0?shadowStructureMultiplier:(dy>0?reflectionGlowMultiplier:1);
        adjusted*=directional;
        result=original+adjusted;
        if(signedHdr<=0.5 && (abs(residualSaturation-1.0)>=1e-6 || abs(residualLightness-1.0)>=1e-6)) {
            candidate=original+adjusted;
            candidate=saturate(candidate);
            float3 oldHsl=NrRgbToHsl(original), newHsl=NrRgbToHsl(candidate);
            newHsl.y=saturate(oldHsl.y+(newHsl.y-oldHsl.y)*residualSaturation);
            newHsl.z=saturate(oldHsl.z+(newHsl.z-oldHsl.z)*residualLightness);
            result=NrHslToRgb(newHsl);
        }
    }
    return signedHdr>0.5?result:saturate(result);
}

[numthreads(16,16,1)] void main(uint3 id:SV_DispatchThreadID){
    uint w,h,nw,nh;baseTex.GetDimensions(w,h);nrInput.GetDimensions(nw,nh);
    if(id.x>=w||id.y>=h)return;
    float4 base=baseTex[id.xy];
    float protection=NrProtection(float2(id.xy)+0.5,uint2(w,h),protectionEnabled,featherPixels,regions);
    if(total==0||protection>=1){outputTex[id.xy]=float4(NrEncodeOutput(base.rgb),base.a);return;}
    float3 delta=0;
    if(w==nw&&h==nh) {
        int2 q=int2(id.xy);
        delta=nrFinal[q].rgb-(residualInput>0.5?float3(0,0,0):nrInput[q].rgb);
    } else {
        float2 pos=(float2(id.xy)+0.5)*float2(nw,nh)/float2(w,h)-0.5;
        int2 origin=(int2)floor(pos);float2 f=frac(pos);delta=0;float weights=0;
        for(int y=0;y<2;++y)for(int x=0;x<2;++x){
            int2 q=clamp(origin+int2(x,y),int2(0,0),int2(nw-1,nh-1));
            float3 low=nrInput[q].rgb;
            float weight=(x?f.x:1-f.x)*(y?f.y:1-f.y);
            if(w!=nw||h!=nh)weight/=1+16*dot(abs(base.rgb-low),NrLumaWeights());
            delta+=(nrFinal[q].rgb-(residualInput>0.5?float3(0,0,0):low))*weight;weights+=weight;
        }
        delta/=max(weights,1e-6);
    }
    delta=NrApplyFine(base.rgb,delta)-base.rgb;float3 rawDelta=delta;
    if(darken!=1||brighten!=1)delta=min(delta,0)*darken+max(delta,0)*brighten;
    if(color!=1||luminance!=1){float dy=dot(delta,NrLumaWeights());delta=dy*luminance+(delta-dy)*color;}
    delta*=total*(1-protection);
    float3 result=float3(shadowSafe(base.r,rawDelta.r,delta.r),
                         shadowSafe(base.g,rawDelta.g,delta.g),
                         shadowSafe(base.b,rawDelta.b,delta.b));
    outputTex[id.xy]=float4(NrEncodeOutput(signedHdr>0.5?result:max(0,result)),base.a);
}
