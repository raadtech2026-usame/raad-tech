import 'dart:typed_data';

/// G.711 A-law encoder: converts 16-bit linear PCM samples to 8-bit A-law bytes.
/// Mirrors `frontend/src/shared/audio/g711a.ts` and JT1078 relay specification (ADR-0036).
///
/// Device input rate: 8000 Hz, mono.
/// Each 40ms frame contains 320 samples (320 bytes in A-law).
const List<int> _segAend = [0x1f, 0x3f, 0x7f, 0xff, 0x1ff, 0x3ff, 0x7ff, 0xfff];

int _search(int val, List<int> table) {
  for (int i = 0; i < table.length; i++) {
    if (val <= table[i]) return i;
  }
  return table.length;
}

/// Converts a single signed 16-bit linear PCM sample into an 8-bit A-law byte.
int linearToALaw(int sampleIn) {
  int pcmVal = sampleIn.clamp(-32768, 32767) >> 3;
  int mask;
  if (pcmVal >= 0) {
    mask = 0xd5;
  } else {
    mask = 0x55;
    pcmVal = -pcmVal - 1;
  }

  final seg = _search(pcmVal, _segAend);
  if (seg >= 8) {
    return 0x7f ^ mask;
  }
  int aVal = seg << 4;
  aVal |= seg < 2 ? (pcmVal >> 1) & 0x0f : (pcmVal >> seg) & 0x0f;
  return aVal ^ mask;
}

/// Converts little-endian 16-bit signed PCM byte buffer to 8-bit A-law bytes.
Uint8List encodePcm16ToALaw(Uint8List pcm16Bytes) {
  final sampleCount = pcm16Bytes.length ~/ 2;
  final out = Uint8List(sampleCount);
  final byteData = ByteData.sublistView(pcm16Bytes);
  for (int i = 0; i < sampleCount; i++) {
    final sample = byteData.getInt16(i * 2, Endian.little);
    out[i] = linearToALaw(sample);
  }
  return out;
}
