#version 440
layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    float time;
    float depth;
    vec2 resolution;
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

void main() {
    vec2 uv = qt_TexCoord0;
    float fieldDepth = clamp(depth, 0.0, 1.0);
    float timeA = time * 6.28318;

    float broadWave = sin(uv.y * 9.0 + timeA * 0.22) * (0.0014 + fieldDepth * 0.0042);
    float crossWave = cos(uv.x * 7.6 - timeA * 0.17) * (0.0009 + fieldDepth * 0.0026);
    float paneWobble = noise(vec2(uv.x * 3.2, uv.y * 1.6) + vec2(time * 0.08, -time * 0.04));
    vec2 warped = uv + vec2(broadWave + (paneWobble - 0.5) * (0.001 + fieldDepth * 0.0034),
                            crossWave + (paneWobble - 0.5) * (0.0006 + fieldDepth * 0.0022));

    float body = noise(warped * vec2(4.0, 7.0) + vec2(time * 0.22, -time * 0.12));
    float weather = noise(warped * vec2(16.0, 5.0) + vec2(-time * 0.04, time * 0.06));
    float fogging = noise(warped * vec2(34.0, 20.0) + vec2(time * 0.1, time * 0.04));
    float pane = smoothstep(0.46, 0.03, abs(fract((warped.x + weather * 0.012) * 2.4) - 0.5));
    float causticBand = sin((warped.y * 20.0 + warped.x * 9.0) + timeA * 0.46 + body * 2.2) * 0.5 + 0.5;
    float caustic = smoothstep(0.72, 1.0, causticBand) * (0.2 + fieldDepth * 0.5);
    float oldRipple = smoothstep(0.58, 0.98, noise(warped * vec2(9.0, 13.0) + vec2(time * 0.16, -time * 0.08)));

    vec3 base = mix(vec3(0.012, 0.028, 0.036), vec3(0.026, 0.052, 0.062), fieldDepth);
    vec3 tint = base + vec3(0.020, 0.032, 0.036) * body;
    vec3 paneTint = vec3(0.024, 0.044, 0.052) * pane * (0.08 + fieldDepth * 0.18);
    vec3 causticTint = vec3(0.070, 0.105, 0.110) * caustic * (0.018 + fieldDepth * 0.055);
    vec3 weatherTint = vec3(0.018, 0.021, 0.022) * weather * (0.08 + fieldDepth * 0.12);
    vec3 fogTint = vec3(0.012, 0.017, 0.021) * fogging * (0.05 + fieldDepth * 0.08);
    vec3 rippleTint = vec3(0.028, 0.042, 0.046) * oldRipple * (0.012 + fieldDepth * 0.024);

    float alpha = mix(0.014, 0.105, fieldDepth) + pane * 0.008 + caustic * 0.012 + oldRipple * 0.006;
    fragColor = vec4(tint + paneTint + causticTint + weatherTint + fogTint + rippleTint, alpha) * qt_Opacity;
}
