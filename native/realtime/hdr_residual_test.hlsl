// SPDX-License-Identifier: GPL-3.0-only
#include "hdr_residual.hlsli"
Texture2D<float4> Base : register(t0);
Texture2D<float4> Nr : register(t1);
RWTexture2D<float4> Output : register(u0);
cbuffer Controls : register(b0) {float Multiplier, Shadows, Highlights, Saturation, Lightness; float3 Padding;};
[numthreads(8,8,1)]
void main(uint3 id : SV_DispatchThreadID) {
    uint w,h; Base.GetDimensions(w,h); if (id.x>=w || id.y>=h) return;
    float4 base=Base[id.xy];
    Output[id.xy]=float4(ApplyHdrResidualControls(base.rgb,Nr[id.xy].rgb-base.rgb,
        Multiplier,Shadows,Highlights,Saturation,Lightness),base.a);
}
