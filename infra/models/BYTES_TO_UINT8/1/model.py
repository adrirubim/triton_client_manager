import io

import numpy as np
import triton_python_backend_utils as pb_utils
from PIL import Image


class TritonPythonModel:
    def initialize(self, args):
        pass

    def execute(self, requests):
        responses = []
        for req in requests:
            bytes_t = pb_utils.get_input_tensor_by_name(req, "BYTES")
            size_t = pb_utils.get_input_tensor_by_name(req, "IMG_SIZE")
            if bytes_t is None or size_t is None:
                responses.append(pb_utils.InferenceResponse(error=pb_utils.TritonError("Missing BYTES or IMG_SIZE")))
                continue
            try:
                size = size_t.as_numpy().astype(np.int32).reshape(-1)
                if size.size != 2:
                    raise ValueError("IMG_SIZE must be a 2-element int32 tensor: [H, W]")
                h = int(size[0])
                w = int(size[1])
                if h <= 0 or w <= 0:
                    raise ValueError("IMG_SIZE values must be > 0")

                raw = bytes(bytes_t.as_numpy().astype(np.uint8).tobytes())
                img = Image.open(io.BytesIO(raw)).convert("RGB")
                img = img.resize((w, h))  # PIL uses (W, H)
                arr = np.asarray(img, dtype=np.uint8)  # HWC
                arr = np.transpose(arr, (2, 0, 1))  # CHW
                out1 = pb_utils.Tensor("IMG_UINT8", arr)
                out2 = pb_utils.Tensor("IMG_ORIGINAL", np.frombuffer(raw, dtype=np.uint8))
                responses.append(pb_utils.InferenceResponse(output_tensors=[out1, out2]))
            except Exception as e:
                responses.append(pb_utils.InferenceResponse(error=pb_utils.TritonError(str(e))))
        return responses
