# Báo cáo Đánh giá Hiệu năng Lab 16

## Thông tin chung (Metadata)
- Bộ dữ liệu (Dataset): hotpot_golden.json
- Chế độ chạy (Mode): llm
- Số lượng bản ghi (Records): 40
- Các Agent: react, reflexion

## Kết quả tóm tắt (Summary)
| Chỉ số (Metric) | ReAct | Reflexion | Chênh lệch (Delta) |
|---|---:|---:|---:|
| Tỉ lệ khớp chính xác (EM) | 1.0 | 1.0 | 0.0 |
| Số lần thử trung bình (Avg attempts) | 1 | 1.1 | 0.1 |
| Ước tính token trung bình (Avg token estimate) | 242.7 | 367.65 | 124.95 |
| Độ trễ trung bình (Avg latency - ms) | 8060.45 | 7797.15 | -263.3 |

## Phân tích các dạng lỗi (Failure modes)
```json
{
  "react": {
    "none": 20
  },
  "overall": {
    "none": 40
  },
  "reflexion": {
    "none": 20
  }
}
```

## Các phần mở rộng đã triển khai (Extensions implemented)
- structured_evaluator
- reflection_memory
- benchmark_report_json
- mock_mode_for_autograding

## Thảo luận (Discussion)
Reflexion giúp cải thiện câu trả lời khi lần thử đầu tiên dừng lại sau bước đầu tiên (hop đầu) hoặc bị lệch sang một thực thể sai ở bước thứ hai (entity drift). Thử nghiệm này so sánh mô hình cơ sở ReAct chạy một lần với tác nhân Reflexion chạy nhiều lần, từ đó báo cáo phản ánh sự đánh đổi giữa độ chính xác và chi phí tài nguyên. Các dạng lỗi (failure modes) chính cần xem xét bao gồm: suy luận đa bước chưa hoàn thiện (incomplete multi-hop reasoning), lệch thực thể khi đi theo đoạn văn bổ trợ sai (entity drift), và câu trả lời cuối cùng bị sai mặc dù có vẻ hợp lý nhưng không được chứng thực bởi ngữ cảnh. Reflexion có thể khắc phục một số lỗi này bằng cách chuyển đổi phản hồi từ bộ đánh giá (evaluator) thành chiến thuật hành động cụ thể tiếp theo, tuy nhiên nó cũng làm tăng số lần thử, lượng token tiêu thụ và độ trễ (latency).
