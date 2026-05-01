#version 440
layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    float time;
    vec2 resolution;
    float intensity;
    float density;
    float driftSpeed;
    vec2 driftDirection;
    float flowScale;
    float crosswindWobble;
    float rollingSpeed;
    float wispStretch;
    float noiseScale;
    float edgeDensity;
    float lowerFogBias;
    float centerClearRadius;
    float foregroundAmount;
    float sampleCount;
    float opacityLimit;
    vec2 protectedCenter;
    float protectedRadius;
    float centerClearStrength;
    vec2 anchorCenter;
    float anchorRadius;
    float cardClearStrength;
    float foregroundOpacityLimit;
    vec4 colorNear;
    vec4 colorFar;
};

float hash31(vec3 p) {
    p = fract(p * 0.1031);
    p += dot(p, p.yzx + 33.33);
    return fract((p.x + p.y) * p.z);
}

float noise3(vec3 p) {
    vec3 i = floor(p);
    vec3 f = fract(p);
    vec3 u = f * f * (3.0 - 2.0 * f);

    float n000 = hash31(i + vec3(0.0, 0.0, 0.0));
    float n100 = hash31(i + vec3(1.0, 0.0, 0.0));
    float n010 = hash31(i + vec3(0.0, 1.0, 0.0));
    float n110 = hash31(i + vec3(1.0, 1.0, 0.0));
    float n001 = hash31(i + vec3(0.0, 0.0, 1.0));
    float n101 = hash31(i + vec3(1.0, 0.0, 1.0));
    float n011 = hash31(i + vec3(0.0, 1.0, 1.0));
    float n111 = hash31(i + vec3(1.0, 1.0, 1.0));

    float nx00 = mix(n000, n100, u.x);
    float nx10 = mix(n010, n110, u.x);
    float nx01 = mix(n001, n101, u.x);
    float nx11 = mix(n011, n111, u.x);
    float nxy0 = mix(nx00, nx10, u.y);
    float nxy1 = mix(nx01, nx11, u.y);
    return mix(nxy0, nxy1, u.z);
}

float fbm3(vec3 p) {
    float value = 0.0;
    float amplitude = 0.5;
    for (int i = 0; i < 4; ++i) {
        value += noise3(p) * amplitude;
        p = p * 2.02 + vec3(11.7, 3.1, 5.4);
        amplitude *= 0.5;
    }
    return value;
}

float edgeWeight(vec2 uv) {
    float sideDistance = min(uv.x, 1.0 - uv.x);
    float side = 1.0 - smoothstep(0.0, 0.24, sideDistance);
    float bottom = 1.0 - smoothstep(0.0, 0.34, 1.0 - uv.y);
    float top = (1.0 - smoothstep(0.0, 0.18, uv.y)) * 0.20;
    return clamp(max(max(side * 0.72, bottom), top), 0.0, 1.0);
}

void main() {
    vec2 uv = qt_TexCoord0;
    float samples = clamp(sampleCount, 1.0, 28.0);
    float t = time * 6.2831853;
    float aspect = max(resolution.x / max(resolution.y, 1.0), 0.1);
    vec2 centeredUv = vec2((uv.x - 0.5) * aspect, uv.y - 0.54);
    float directionLength = length(driftDirection);
    vec2 flowDirection = directionLength > 0.001 ? driftDirection / directionLength : vec2(0.0, 0.0);
    vec2 crossAxis = directionLength > 0.001 ? vec2(-flowDirection.y, flowDirection.x) : vec2(0.0, 1.0);
    float effectiveStretch = clamp(wispStretch, 0.8, 2.8);
    float flowDistance = time * driftSpeed * clamp(flowScale, 0.2, 2.0) * 10.0;
    float rollT = t * max(0.15, rollingSpeed / 0.035);
    float globalWobble = (
        fbm3(vec3(uv * vec2(0.82, 0.42) + vec2(time * 0.018, -time * 0.006), rollT * 0.075))
        - 0.5
    ) * crosswindWobble * 0.10;
    vec2 globalFlowUv = uv - flowDirection * flowDistance + crossAxis * globalWobble;

    float lowerMask = mix(0.32, 1.0, smoothstep(0.16, 1.0, uv.y));
    lowerMask = mix(1.0, lowerMask, clamp(lowerFogBias, 0.0, 1.0));

    float edgeMask = mix(0.44, 1.0, edgeWeight(uv) * clamp(edgeDensity, 0.0, 1.0));
    float lowerShelf = smoothstep(0.50, 1.0, uv.y);
    vec2 shelfUv = vec2(
        (globalFlowUv.x + globalFlowUv.y * 0.24) / effectiveStretch,
        globalFlowUv.y * 0.58
    );
    float broadShelfNoise = fbm3(vec3(
        shelfUv * vec2(1.75, 0.84) * noiseScale,
        rollT * 0.034
    ));
    float lowerRoll = lowerShelf * mix(0.82, 1.24, smoothstep(0.28, 0.82, broadShelfNoise));
    lowerRoll *= mix(0.86, 1.20, edgeWeight(uv));

    float clearStrength = clamp(centerClearStrength, 0.0, 1.0);
    float centerDistance = length(centeredUv / vec2(max(centerClearRadius, 0.08) * 1.28, max(centerClearRadius, 0.08)));
    float centerClear = smoothstep(0.54, 1.18, centerDistance);
    centerClear = mix(1.0, centerClear, clearStrength * 0.88);

    vec2 protectedDelta = vec2((uv.x - protectedCenter.x) * aspect, uv.y - protectedCenter.y);
    float protectedDistance = length(protectedDelta / vec2(max(protectedRadius, 0.08) * 1.42, max(protectedRadius, 0.08)));
    float protectedClear = smoothstep(0.52, 1.22, protectedDistance);
    protectedClear = mix(1.0, protectedClear, clearStrength * clamp(cardClearStrength, 0.0, 1.0));

    vec2 anchorDelta = vec2((uv.x - anchorCenter.x) * aspect, uv.y - anchorCenter.y);
    float anchorDistance = length(anchorDelta / vec2(max(anchorRadius, 0.08) * 1.20, max(anchorRadius, 0.08)));
    float anchorClear = smoothstep(0.42, 1.16, anchorDistance);
    anchorClear = mix(1.0, anchorClear, clearStrength * 0.72);

    float readabilityMask = min(centerClear, min(protectedClear, anchorClear));
    float screenFeather = smoothstep(0.0, 0.025, uv.x) * (1.0 - smoothstep(0.975, 1.0, uv.x))
                        * smoothstep(0.0, 0.025, uv.y) * (1.0 - smoothstep(0.975, 1.0, uv.y));

    float accumulated = 0.0;
    float nearAmount = 0.0;

    for (int i = 0; i < 28; ++i) {
        if (float(i) >= samples) {
            break;
        }

        float z = (float(i) + 0.5) / samples;
        float parallax = mix(0.58, 1.82, z);
        float layerFlow = flowDistance * mix(0.74, 1.36, z);
        float layerWobble = (
            fbm3(vec3(uv * vec2(0.72, 0.38) + vec2(z * 2.1, -z * 0.7), rollT * 0.10))
            - 0.5
        ) * crosswindWobble * mix(0.05, 0.13, z);
        vec2 layerUv = uv - flowDirection * layerFlow + crossAxis * layerWobble;
        float diagonalShear = (layerUv.y - 0.5) * mix(0.18, 0.36, z);
        vec2 stretchedUv = vec2(
            (layerUv.x + diagonalShear) / effectiveStretch,
            layerUv.y * mix(1.18, 1.46, z)
        );
        vec2 rollUv = stretchedUv * vec2(2.15, 0.82) * noiseScale * parallax;
        vec3 p = vec3(rollUv, z * 2.8 + rollT * 0.050);

        float broad = fbm3(p * 1.08);
        vec2 warp = vec2(
            fbm3(p * 1.6 + vec3(7.1, 0.0, 1.3)),
            fbm3(p * 1.4 + vec3(1.9, 5.2, 2.7))
        ) - vec2(0.5);
        float wisp = fbm3(vec3(rollUv + warp * 0.34, z * 3.4 + rollT * 0.070) * 2.0);
        float filament = fbm3(vec3(rollUv * vec2(3.8, 1.05) + warp * 0.58, z * 4.2 - rollT * 0.045));

        float densityField = broad * 0.50 + wisp * 0.36 + filament * 0.14;
        densityField = smoothstep(0.16, 0.94, densityField);
        float threshold = mix(0.48, 0.23, lowerMask * 0.60 + edgeWeight(uv) * 0.34);
        float sampleFog = smoothstep(threshold, 0.82, densityField);
        float verticalStrata = exp(-pow((uv.y - mix(0.82, 0.64, z)) / mix(0.22, 0.36, z), 2.0));
        verticalStrata = max(0.16, verticalStrata);
        float depthWeight = mix(0.76, 1.22, z);

        accumulated += sampleFog * verticalStrata * depthWeight;
        nearAmount += sampleFog * z;
    }

    accumulated /= samples;
    nearAmount /= samples;

    vec2 foregroundUv = globalFlowUv + crossAxis * (
        fbm3(vec3(globalFlowUv * vec2(1.3, 0.62), rollT * 0.08)) - 0.5
    ) * crosswindWobble * 0.06;
    vec2 foregroundDomain = vec2(
        (foregroundUv.x + foregroundUv.y * 0.18) / max(0.8, effectiveStretch * 0.82),
        foregroundUv.y * 1.28
    );
    float foregroundWisps = foregroundAmount * smoothstep(0.42, 0.72, fbm3(vec3(foregroundDomain * vec2(3.9, 1.2), rollT * 0.052)));
    foregroundWisps *= mix(0.40, 1.0, edgeWeight(uv));
    foregroundWisps *= readabilityMask;

    float fogBody = accumulated * density * 2.88 * lowerMask * edgeMask * readabilityMask * screenFeather;
    fogBody *= mix(0.94, 1.24, lowerRoll);
    float fog = fogBody + foregroundWisps * screenFeather;
    fog = smoothstep(0.004, 0.48, clamp(fog * 4.24, 0.0, 1.0));

    float bodyAlpha = min(opacityLimit, fog * intensity * 1.30);
    float foregroundAlpha = min(clamp(foregroundOpacityLimit, 0.0, opacityLimit), foregroundWisps * intensity * 0.88);
    float alpha = min(opacityLimit, max(bodyAlpha, foregroundAlpha));
    vec3 color = mix(colorFar.rgb, colorNear.rgb, clamp(nearAmount * 1.9 + foregroundWisps, 0.0, 1.0));
    color *= mix(0.78, 1.0, alpha / max(opacityLimit, 0.001));

    fragColor = vec4(color * alpha, alpha) * qt_Opacity;
}
