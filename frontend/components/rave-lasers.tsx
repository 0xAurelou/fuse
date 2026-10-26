import { memo } from 'react';

export const RaveLasers = memo(function RaveLasers() {
  return <div className="rave-lasers" aria-hidden="true">
    <div className="rave-laser-emitter rave-laser-left"><i/><i/><i/><i/><i/></div>
    <div className="rave-laser-emitter rave-laser-right"><i/><i/><i/><i/><i/></div>
  </div>;
});
