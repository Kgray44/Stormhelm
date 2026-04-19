#version 440
layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    float time;
    float depth;
    float globalPresence;
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
        p = p * 2.02 + vec2(4.7, 2.3);
        amplitude *= 0.5;
    }
    return value;
}

void main() {
    vec2 uv = qt_TexCoord0;
    float t = time * 6.28318;
    float strength = clamp(depth, 0.0, 1.0);
    float wash = clamp(globalPresence, 0.0, 1.0);

    vec2 driftA = vec2(t * 0.018, -t * 0.009);
    vec2 driftB = vec2(-t * 0.010, t * 0.006);
    vec2 driftC = vec2(t * 0.008, t * 0.004);
    float layerA = fbm(uv * vec2(1.05, 0.62) + driftA);
    float layerB = fbm(uv * vec2(1.72, 0.94) + driftB);
    float pressure = fbm(uv * vec2(0.64, 0.46) + driftC);

    float mist = smoothstep(0.44, 0.70, layerA * 0.58 + layerB * 0.28 + pressure * 0.14);

    vec2 offset = (uv - focusPoint) / max(spread, vec2(0.001));
    float centered = exp(-dot(offset, offset));
    float bandYOffsetA = sin(t * 0.12 + pressure * 1.7) * spread.y * 0.46;
    float bandYOffsetB = cos(t * 0.09 + layerB * 1.9) * spread.y * 0.34;
    float horizontalBandA = exp(-pow((uv.y - (focusPoint.y + bandYOffsetA)) / max(spread.y * 1.35, 0.001), 2.0))
                          * exp(-pow((uv.x - focusPoint.x) / max(spread.x * 1.05, 0.001), 2.0));
    float horizontalBandB = exp(-pow((uv.y - (focusPoint.y - bandYOffsetB)) / max(spread.y * 1.85, 0.001), 2.0))
                          * exp(-pow((uv.x - focusPoint.x) / max(spread.x * 1.32, 0.001), 2.0));
    float edgeFade = smoothstep(0.0, 0.18, uv.x) * smoothstep(1.0, 0.82, uv.x)
                   * smoothstep(0.0, 0.12, uv.y) * smoothstep(1.0, 0.88, uv.y);
    float fieldWash = wash * (0.45 + pressure * 0.55);
    float mask = max(centered * 0.92, horizontalBandA * 0.98)
               + horizontalBandB * 0.72
               + fieldWash;
    mask = clamp(mask, 0.0, 1.0);

    vec3 tint = mix(vec3(0.34, 0.42, 0.47), vec3(0.24, 0.31, 0.36), pressure);
    float alpha = mist * mask * edgeFade * mix(0.024, 0.056, smoothstep(0.05, 0.16, strength));

    fragColor = vec4(tint * alpha, alpha) * qt_Opacity;
}
