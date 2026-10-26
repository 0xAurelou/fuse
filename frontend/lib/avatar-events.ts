// Presentation-only event detection. These helpers never submit trading commands.
// Three avatar states only: dance (no reaction), win cheer, blown-kiss loss.
export type ObservedStage = { id: string; accepted_sequence: number; status: 'active' | 'pending' | 'survived' | 'exploded' | 'voided' };
export type AvatarReaction = { id: string; kind: 'win' | 'loss'; at: number };
export type AvatarCursor = { hydrated: boolean; sequence: number; statuses: Map<string, ObservedStage['status']> };
export const createAvatarCursor = (): AvatarCursor => ({ hydrated: false, sequence: 0, statuses: new Map() });
const terminal = (status: ObservedStage['status']) => status !== 'active' && status !== 'pending';

export function observeAvatarStages(cursor: AvatarCursor, stages: ObservedStage[], now: number, acceptedReceipt = false): AvatarReaction | null {
  let reaction: AvatarReaction | null = null;
  for (const stage of stages) {
    const previous = cursor.statuses.get(stage.id);
    const fresh = !previous && (acceptedReceipt || cursor.hydrated && stage.accepted_sequence > cursor.sequence);
    const loss = stage.status === 'exploded' && (previous === 'active' || previous === 'pending' || fresh);
    const win = stage.status === 'survived' && (previous === 'active' || previous === 'pending' || fresh);
    if (loss) reaction = { id: `${stage.id}:loss`, kind: 'loss', at: now };
    else if (win && reaction?.kind !== 'loss') reaction = { id: `${stage.id}:win`, kind: 'win', at: now };
    // Terminal outcomes cannot be re-armed by a delayed active snapshot.
    if (!previous || !terminal(previous)) cursor.statuses.set(stage.id, stage.status);
  }
  for (const stage of stages) cursor.sequence = Math.max(cursor.sequence, stage.accepted_sequence);
  if (!acceptedReceipt) cursor.hydrated = true;
  return reaction;
}
