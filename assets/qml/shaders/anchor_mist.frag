#version 440
layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    float time;
    float depth;
    vec2 focusPoint;
    vec2 spread;
};

float hash(vec2 p) {
    return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123);
}

float noise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    float a = hash(i);
    float b = hash(i + vec2(1.0, 0.0));
    float c = hash(i + vec2(0.0, 1.0));
    float d = hash(i + vec2(1.0, 1.0));
    vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(a, b, u.x) + (c - a) * u.y * (1.0 - u.x) + (d - b) * u.x * u.y;
}

float fbm(vec2 p) {
    float value = 0.0;
    float amplitude = 0.5;
    for (int i = 0; i < 4; ++i) {
        value += noise(p) * amplitude;
        p = p * 2.01 + vec2(4.1, 2.7);
        amplitude *= 0.5;
    }
    return value;
}

void main() {
    vec2 uv = qt_TexCoord0;
    float t = time * 6.28318;
    float strength = clamp(depth, 0.0, 1.0);

    vec2 driftA = vec2(t * 0.010, -t * 0.006);
    vec2 driftB = vec2(-t * 0.007, t * 0.0045);
    vec2 driftC = vec2(t * 0.004, t * 0.0025);

    float layerA = fbm(uv * vec2(0.78, 0.46) + driftA);
    float layerB = fbm(uv * vec2(1.26, 0.70) + driftB);
    float layerC = fbm(uv * vec2(1.92, 1.05) + driftC);
    float pressure = fbm(uv * vec2(0.52, 0.34) + vec2(-t * 0.0025, t * 0.0018));

    float mist = smoothstep(0.42, 0.70, layerA * 0.50 + layerB * 0.31 + layerC * 0.19 + pressure * 0.08);

    vec2 offset = (uv - focusPoint) / max(spread, vec2(0.001));
    float centered = exp(-dot(offset, offset));

    float bandCenterA = focusPoint.y + sin(t * 0.13 + layerB * 2.4) * spread.y * 0.62;
    float bandCenterB = focusPoint.y - cos(t * 0.10 + layerA * 2.1) * spread.y * 0.48;
    float bandA = exp(-pow((uv.y - bandCenterA) / max(spread.y * 1.18, 0.001), 2.0))
                * exp(-pow((uv.x - focusPoint.x) / max(spread.x * 1.20, 0.001), 2.0));
    float bandB = exp(-pow((uv.y - bandCenterB) / max(spread.y * 1.72, 0.001), 2.0))
                * exp(-pow((uv.x - focusPoint.x) / max(spread.x * 1.46, 0.001), 2.0));

    float edgeFade = smoothstep(0.0, 0.12, uv.x) * smoothstep(1.0, 0.88, uv.x)
                   * smoothstep(0.0, 0.12, uv.y) * smoothstep(1.0, 0.90, uv.y);

    float mask = max(centered * 0.86, bandA * 0.96);
    mask = max(mask, bandB * 0.72);
    mask *= edgeFade;

    vec3 tint = mix(vec3(0.68, 0.76, 0.80), vec3(0.48, 0.58, 0.64), pressure);
    float alpha = mist * mask * strength * (0.98 + pressure * 0.36);

    fragColor = vec4(tint * alpha, alpha) * qt_Opacity;
}
