import pandas as pd
import re
import numpy as np


def preprocess_offer(file_path):
    # 엑셀 파일을 DataFrame으로 불러옵니다.
    offer = pd.read_excel(file_path)

    offer.drop(columns=['Unnamed: 0'], inplace=True)
    offer.drop(offer.index[1157], axis=0, inplace=True)
    offer['Capacity'] = offer['Capacity'].astype(int)
    offer['Min Per Session'] = offer['Min Per Session'].astype(int)

    offer['Session'] = offer['Session'].str.upper()
    offer['Lecturer'] = offer['Lecturer'].str.upper()
    offer['CourseCode'] = offer['CourseCode'].str.upper()
    offer['FacultyCode'] = offer['FacultyCode'].str.upper()

    offer['Session'] = offer['Session'].str.replace(r'\(S\)', '', regex=True)

    # "COMBINED TO /"를 복사하여 error 테이블에 저장. 이후 원본 데이터에서 삭제.
    mask = offer['Session'].str.contains("COMBINED TO /", na=False)

    # error 데이터프레임에 해당 행들을 복사하여 저장합니다.
    error = offer[mask].copy()

    # 원본 offer 데이터프레임에서 해당 행들을 삭제합니다.
    offer.drop(offer[mask].index, inplace=True)

    # "GROUP A", "GROUP B", "GROUP C" 등 해당하는 행을 찾고, Session 값을 "LECTURE"로 변경
    offer.loc[offer['Session'].str.contains(r'^GROUP\s+[A-Z]$', na=False), 'Session'] = 'LECTURE'

    group_cols = ['CourseCode', 'FacultyCode', 'Session', 'Capacity', 'Min Per Session', 'Lecturer']

    # 그룹별로 중복된 행을 처리합니다.
    for _, group in offer.groupby(group_cols):
        if len(group) > 1:  # 중복 그룹인 경우
            # 원래 Session 값을 앞뒤 공백 제거 후 사용합니다.
            orig_session = group.iloc[0]['Session'].strip()
            # Session 값이 숫자로 끝나는지 검사 (예: "TUTORIAL 1")
            m = re.search(r'^(.*?)(\d+)$', orig_session)
            if m:
                base = m.group(1).strip()  # 문자 부분 (예: "TUTORIAL")
                start_num = int(m.group(2))  # 기존에 붙은 숫자 (예: 1)
            else:
                base = orig_session
                start_num = 1

            # 그룹 내 각 행에 대해 순차적으로 번호를 붙여 Session 값을 변경합니다.
            for offset, idx in enumerate(group.index):
                new_session = f"{base} {start_num + offset}"
                offer.at[idx, 'Session'] = new_session

    # (초기 전제: offer DataFrame과 error DataFrame이 존재함; error가 없으면 빈 DataFrame 생성)
    if 'error' not in globals():
        error = pd.DataFrame()

    ### Step 1. offer에서 "COMBINED TO" 행 추출 → child_class로 저장, offer에서는 제거
    child_class = offer[offer['Session'].str.contains('COMBINED TO', na=False)].copy()
    offer.drop(child_class.index, inplace=True)

    ### Step 2. child_class의 Session 열에서 과목코드 추출
    child_class['extracted_code'] = child_class['Session'].str.extract(r'COMBINED TO\s+([A-Z0-9]+)', expand=False)

    ### Step 3. child_class 내에서 오류 및 정상/후손 분리

    # (A) "자기 자신 참조" 조건: 추출한 코드가 해당 행의 CourseCode와 같으면 → 오류
    self_ref = child_class['extracted_code'] == child_class['CourseCode']

    # (B) 정상(child) 조건: 자기 자신 참조가 아니고, 추출한 코드가 offer의 CourseCode에 존재하는 경우
    valid_child_mask = (~self_ref) & (child_class['extracted_code'].isin(offer['CourseCode']))

    # (C) 후손(grandchild) 후보: 자기 자신 참조가 아니고, 추출한 코드가 offer에는 없지만, child_class의 CourseCode에는 존재하는 경우
    #     (즉, 부모(대상 CourseCode)가 offer에 없으므로 자식끼리 연결되어 있음을 의미)
    valid_grand_mask = (~self_ref) & (~child_class['extracted_code'].isin(offer['CourseCode'])) & \
                       (child_class['extracted_code'].isin(child_class['CourseCode']))

    # (D) 오류 조건:
    #     - 자기 자신 참조인 경우
    #     - 또는 추출한 코드가 offer에도 child_class에도 존재하지 않는 경우
    error_mask = self_ref | ((~child_class['extracted_code'].isin(offer['CourseCode'])) &
                             (~child_class['extracted_code'].isin(child_class['CourseCode'])))

    # child_class 오류 처리: 추출
    child_error = child_class[error_mask].copy()

    # 정상 child_class (valid_child) 추출
    valid_child = child_class[valid_child_mask].copy()

    # 후보 후손(grandchild) 추출
    candidate_grand = child_class[valid_grand_mask].copy()

    ### Step 4. grand_child_class 내에서 추가 오류 처리
    # 오류 조건 (grandchild): 자기 자신 참조 → 오류
    grand_self_ref = candidate_grand['extracted_code'] == candidate_grand['CourseCode']
    error_grand = candidate_grand[grand_self_ref].copy()

    # 최종 grand_child_class: 후보에서 자기 자신 참조 오류 제거
    grand_child_class = candidate_grand[~grand_self_ref].copy()

    # 최종 error: 기존 child 오류와 후손에서 발생한 오류를 모두 누적
    error_df = pd.concat([child_error, error_grand], ignore_index=True)
    error = pd.concat([error, error_df], ignore_index=True)

    ### 최종 정상 데이터
    # child_class는 valid_child로 업데이트 (offer의 부모가 존재하는 경우)
    child_class = valid_child.copy()
    # grand_child_class는 위에서 구한 대로

    # error DataFrame이 없으면 빈 DataFrame 생성
    if 'error' not in globals():
        error = pd.DataFrame()

    ##############################################
    # 교차검증 1: child_class에서 자기 자신 참조하는 행 처리
    ##############################################
    child_self_ref_mask = (child_class['extracted_code'] == child_class['CourseCode'])
    child_self_ref_errors = child_class[child_self_ref_mask].copy()
    error = pd.concat([error, child_self_ref_errors], ignore_index=True)
    child_class = child_class[~child_self_ref_mask].copy()

    ##############################################
    # 교차검증 2: child_class에서 추출한 과목코드가 offer의 CourseCode에 없음(부모 없음)
    ##############################################
    child_missing_parent_mask = ~child_class['extracted_code'].isin(offer['CourseCode'])
    child_missing_parent_errors = child_class[child_missing_parent_mask].copy()
    error = pd.concat([error, child_missing_parent_errors], ignore_index=True)
    child_class = child_class[~child_missing_parent_mask].copy()

    ##############################################
    # 교차검증 3: offer에서 자기 자신 참조하는 행 처리
    # (offer에 COMBINED TO가 남아있다면 해당 행에 대해 extracted_code를 추출)
    ##############################################
    offer_combined_mask = offer['Session'].str.contains('COMBINED TO', na=False)
    if offer_combined_mask.any():
        offer.loc[offer_combined_mask, 'extracted_code'] = offer.loc[offer_combined_mask, 'Session'].str.extract(
            r'COMBINED TO\s+([A-Z0-9]+)', expand=False)
        offer_self_ref_mask = (offer['extracted_code'] == offer['CourseCode'])
        offer_self_ref_errors = offer[offer_self_ref_mask].copy()
        error = pd.concat([error, offer_self_ref_errors], ignore_index=True)
        offer.drop(offer[offer_self_ref_mask].index, inplace=True)

    ##############################################
    # 교차검증 4: grand_child_class에서 자기 자신 참조하는 행 처리
    ##############################################
    grand_self_ref_mask = (grand_child_class['extracted_code'] == grand_child_class['CourseCode'])
    grand_self_ref_errors = grand_child_class[grand_self_ref_mask].copy()
    error = pd.concat([error, grand_self_ref_errors], ignore_index=True)
    grand_child_class = grand_child_class[~grand_self_ref_mask].copy()

    ##############################################
    # 교차검증 5: grand_child_class에서 추출한 과목코드가 offer의 CourseCode에 없음(부모 없음)
    ##############################################
    grand_missing_parent_mask = ~grand_child_class['extracted_code'].isin(offer['CourseCode'])
    grand_missing_parent_errors = grand_child_class[grand_missing_parent_mask].copy()
    error = pd.concat([error, grand_missing_parent_errors], ignore_index=True)
    grand_child_class = grand_child_class[~grand_missing_parent_mask].copy()

    ##############################################
    # 교차검증 6: 부모(offer 또는 child_class)에서 드랍된 행과 연결된 자식(또는 손자) 행 처리
    # 드랍된 행들의 CourseCode를 모아서, 이 코드를 extracted_code로 사용하는 행이 있다면 error로 처리
    ##############################################
    # 지금까지 error에 추가된 행들의 CourseCode를 모읍니다.
    dropped_codes = set(error['CourseCode'].unique())

    # child_class에서 연결된 자식 행 검사
    child_linked_mask = child_class['extracted_code'].isin(dropped_codes)
    child_linked_errors = child_class[child_linked_mask].copy()
    error = pd.concat([error, child_linked_errors], ignore_index=True)
    child_class = child_class[~child_linked_mask].copy()

    # grand_child_class에서 연결된 손자 행 검사
    grand_linked_mask = grand_child_class['extracted_code'].isin(dropped_codes)
    grand_linked_errors = grand_child_class[grand_linked_mask].copy()
    error = pd.concat([error, grand_linked_errors], ignore_index=True)
    grand_child_class = grand_child_class[~grand_linked_mask].copy()

    # child_class의 각 행을 순회하며 조건에 맞는 offer 행의 Capacity에 child_class의 Capacity를 합산합니다.
    for idx, child_row in child_class.iterrows():
        # 조건: offer의 CourseCode, Min Per Session, Lecturer가 child_row의 extracted_code, Min Per Session, Lecturer와 일치
        mask = (
                (offer['CourseCode'] == child_row['extracted_code']) &
                (offer['Min Per Session'] == child_row['Min Per Session']) &
                (offer['Lecturer'] == child_row['Lecturer'])
        )
        # 일치하는 행이 있다면, offer의 Capacity에 child_row의 Capacity를 더함
        if mask.any():
            offer.loc[mask, 'Capacity'] += child_row['Capacity']

    # 기존 조건
    conditions = [
        offer['Session'].str.contains('LECTURE & TUTORIAL', na=False, case=False),
        offer['Session'].str.contains('TUTORIAL', na=False, case=False),
        offer['Session'].str.contains('LECTURE', na=False, case=False),
        offer['Session'].str.contains('LAB', na=False, case=False),
        offer['Session'].str.contains('PBL 1', na=False, case=False),
        offer['Session'].str.contains('HAND DRAWING|CAD DRAWING 2|CAD DRAWING 1', na=False, case=False),
        offer['Session'].str.contains('KITCHEN', na=False, case=False),
        offer['Session'].str.contains('OPTOM CLINIC|SOO - EXAM CLINIC', na=False, case=False)
    ]

    # 기존 선택지 + 새 선택지
    choices = [
        'GENERAL',
        'TUTORIAL',
        'LECTURE',
        'LAB',
        'PBL',
        'ART',
        'KITCHEN',
        'LECTURE'
    ]

    print(f'condition : {conditions}')
    print(f'choices : {choices}')

    # 조건을 적용하여 'Category' 열 생성
    offer['Category'] = np.select(conditions, choices, default=None).astype(object)

    return offer
