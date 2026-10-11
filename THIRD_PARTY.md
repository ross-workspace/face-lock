# Third-party components

The application's MIT license does not replace the licenses of its dependencies or downloaded model assets.

The pinned model URLs and SHA-256 digests are in [`models/models.json`](models/models.json). Model weights are downloaded during setup and excluded from Git. The OpenCV notices are kept verbatim:

- YuNet: [included MIT notice](models/face_detection_yunet-LICENSE.txt), [upstream notice at the pinned revision](https://github.com/opencv/opencv_zoo/blob/47534e27c9851bb1128ccc0102f1145e27f23f98/models/face_detection_yunet/LICENSE).
- SFace: [included Apache-2.0 notice](models/face_recognition_sface-LICENSE.txt), [upstream notice at the pinned revision](https://github.com/opencv/opencv_zoo/blob/47534e27c9851bb1128ccc0102f1145e27f23f98/models/face_recognition_sface/LICENSE).

MediaPipe's source license is [published upstream](https://github.com/google-ai-edge/mediapipe/blob/master/LICENSE). Its face, hand, and pose assets come from the upstream URLs recorded in the model manifest. Check the relevant upstream model documentation before redistributing model weights or a packaged application.

Python package names and versions are recorded in `requirements.txt`, `requirements-dev.txt`, and `requirements-lock.txt`. Those packages retain their own licensing terms. This source repository does not include a prebuilt application or vendored dependency code.

The README's camera illustration depicts a fictional adult and is identified as a synthetic example. It is not a live-camera recognition result. Actual UI screenshots use demonstration data.

## Platform packaging

macOS-only PyObjC requirements use environment markers. Windows uses native user-scoped DPAPI for stored keys and does not install PyObjC. The pinned MediaPipe 1.1.0 [PyPI metadata](https://pypi.org/pypi/mediapipe/1.1.0/json) includes a `win_amd64` wheel. Availability of a wheel does not establish successful application packaging; run the native build checks before distributing an artifact.

The MediaPipe package also publishes a privacy notice covering on-device inputs and performance/utilization metrics sent to Google. Review it before making runtime privacy claims.
