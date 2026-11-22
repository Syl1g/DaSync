import { ReactNode } from 'react';
import { Pressable, StyleProp, StyleSheet, Text, View, ViewStyle } from 'react-native';
import Svg, { Circle, Defs, LinearGradient, Path, Rect, Stop } from 'react-native-svg';
import { C } from './theme';

export function Logo({ size = 40 }: { size?: number }) {
  return (
    <Svg width={size} height={size} viewBox="0 0 64 64">
      <Defs>
        <LinearGradient id="g1" gradientUnits="userSpaceOnUse" x1="0" y1="17" x2="0" y2="53">
          <Stop offset="0" stopColor="#6ee7ff" />
          <Stop offset="1" stopColor="#60a5fa" />
        </LinearGradient>
        <LinearGradient id="g2" gradientUnits="userSpaceOnUse" x1="0" y1="11" x2="0" y2="47">
          <Stop offset="0" stopColor="#818cf8" />
          <Stop offset="1" stopColor="#c084fc" />
        </LinearGradient>
        <LinearGradient id="db" x1="0" y1="0" x2="0" y2="1">
          <Stop offset="0" stopColor="#171d44" />
          <Stop offset="1" stopColor="#0b1020" />
        </LinearGradient>
      </Defs>
      <Rect width="64" height="64" rx="16" fill="url(#db)" />
      <Rect x="15" y="17" width="10" height="36" rx="5" fill="url(#g1)" />
      <Path d="M31 13A16 16 0 0 1 31 45Z" fill="url(#g2)" stroke="url(#g2)" strokeWidth="4" strokeLinejoin="round" />
    </Svg>
  );
}

type BtnProps = {
  title: string;
  onPress?: () => void;
  kind?: 'default' | 'primary' | 'danger';
  active?: boolean;
  style?: StyleProp<ViewStyle>;
  disabled?: boolean;
};

export function Btn({ title, onPress, kind = 'default', active, style, disabled }: BtnProps) {
  const primary = kind === 'primary' || active;
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled}
      style={({ pressed }) => [
        s.btn,
        primary && s.btnPrimary,
        pressed && { opacity: 0.7, transform: [{ scale: 0.97 }] },
        disabled && { opacity: 0.4 },
        style,
      ]}
    >
      <Text style={[s.btnText, primary && { color: '#06141f' }, kind === 'danger' && { color: C.bad }]}>{title}</Text>
    </Pressable>
  );
}

export function Card({ children, style }: { children: ReactNode; style?: StyleProp<ViewStyle> }) {
  return <View style={[s.card, style]}>{children}</View>;
}

export function Ring({ value, label, sub, color }: { value: number; label: string; sub: string; color: string }) {
  const R = 34, Cc = 2 * Math.PI * R;
  return (
    <View style={{ alignItems: 'center', width: '50%', paddingVertical: 10 }}>
      <View style={{ width: 104, height: 104, alignItems: 'center', justifyContent: 'center' }}>
        <Svg width={104} height={104} viewBox="0 0 80 80" style={{ position: 'absolute' }}>
          <Circle cx="40" cy="40" r={R} stroke="#222a4a" strokeWidth="7" fill="none" />
          <Circle
            cx="40" cy="40" r={R} stroke={color} strokeWidth="7" fill="none" strokeLinecap="round"
            strokeDasharray={`${(Cc * Math.min(value, 100)) / 100} ${Cc}`} rotation={-90} origin="40, 40"
          />
        </Svg>
        <Text style={{ color: C.ink, fontSize: 22, fontWeight: '700' }}>{Math.round(value)}%</Text>
      </View>
      <Text style={{ color: C.ink, fontWeight: '600', marginTop: 4 }}>{label}</Text>
      <Text style={{ color: C.dim, fontSize: 12, marginTop: 2 }}>{sub}</Text>
    </View>
  );
}

const s = StyleSheet.create({
  btn: {
    minHeight: 52, borderRadius: 16, borderWidth: 1, borderColor: C.line, backgroundColor: C.card,
    alignItems: 'center', justifyContent: 'center', paddingHorizontal: 14,
  },
  btnPrimary: { backgroundColor: C.accent, borderColor: C.accent },
  btnText: { color: C.ink, fontWeight: '600', fontSize: 15 },
  card: { backgroundColor: C.card, borderColor: C.line, borderWidth: 1, borderRadius: 20, padding: 16 },
});
